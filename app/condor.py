"""Wrapper around htcondor Python bindings.

Tries to import htcondor2 (v25.x+) first, then falls back to htcondor (v1 API).
"""

from __future__ import annotations

import getpass
import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Default to only showing the current user's jobs for performance
CURRENT_USER = getpass.getuser()
DEFAULT_CONSTRAINT = f'Owner == "{CURRENT_USER}"'

# Timeout for schedd queries (seconds) — prevents hanging on unresponsive daemons
SCHEDD_QUERY_TIMEOUT = 15

# Shared thread pool for running schedd queries with a timeout
_schedd_executor = ThreadPoolExecutor(max_workers=4)

# --- Attempt to import the HTCondor bindings ---
try:
    import htcondor2 as htcondor
    import classad2 as classad  # noqa: F401

    logger.info("Using htcondor2 (v2 API)")
except ImportError:
    import htcondor  # type: ignore[no-redef]
    import classad  # type: ignore[no-redef]  # noqa: F401

    logger.info("Using htcondor (v1 API)")


# Human-readable status names
JOB_STATUS_MAP: dict[int, str] = {
    1: "Idle",
    2: "Running",
    3: "Removed",
    4: "Completed",
    5: "Held",
    6: "Transferring Output",
    7: "Suspended",
}

# Default projection for job queries — keeps payloads small
DEFAULT_PROJECTION: list[str] = [
    "ClusterId",
    "ProcId",
    "JobStatus",
    "Owner",
    "Cmd",
    "Args",
    "RequestCpus",
    "RequestMemory",
    "RequestDisk",
    "QDate",
    "JobStartDate",
    "CompletionDate",
    "HoldReason",
    "RemoteHost",
    "ImageSize",
    "DiskUsage",
    "ExitCode",
    "ExitBySignal",
    "JobCurrentStartDate",
    "NumJobStarts",
    "NumShadowStarts",
    "JobBatchName",
    "RemoteWallClockTime",
    "CumulativeRemoteSysCpu",
    "CumulativeRemoteUserCpu",
]

# ---------------------------------------------------------------------------
# TTL Cache — prevents hammering the schedd on rapid page loads
# ---------------------------------------------------------------------------
# Separate caches with different TTLs:
#   - Active jobs: short TTL (5s) since state changes frequently
#   - History: longer TTL (30s) since historical data is static
#   - Status counts: short TTL (5s) to keep dashboard stats current
# Each cache holds up to 256 distinct query keys.

_query_cache: TTLCache = TTLCache(maxsize=256, ttl=5.0)
_history_cache: TTLCache = TTLCache(maxsize=256, ttl=30.0)
_counts_cache: TTLCache = TTLCache(maxsize=16, ttl=5.0)


def _cache_key(prefix: str, constraint: str, projection: tuple[str, ...] | None) -> str:
    """Build a deterministic cache key from function name and arguments."""
    proj_str = ",".join(sorted(projection)) if projection else "default"
    return f"{prefix}:{constraint}:{proj_str}"


def clear_cache() -> None:
    """Clear all cached data (called after submits/actions so new state is visible)."""
    _query_cache.clear()
    _history_cache.clear()
    _counts_cache.clear()


# ---------------------------------------------------------------------------
# Daemon availability check
# ---------------------------------------------------------------------------


def daemon_available() -> bool:
    """Quick check if the HTCondor scheduler daemon (schedd) is reachable.

    Tries a lightweight ``schedd.query(limit=1)`` and returns ``True`` if
    it succeeds.  If the daemon is unreachable or the Python bindings are
    not installed, returns ``False``.

    The caller should **not** rely on this as a gate — the rest of the API
    gracefully returns empty results when the daemon is unavailable.
    """
    try:
        schedd = get_schedd()
        schedd.query(constraint="JobStatus == 1", projection=["ClusterId"], limit=1)
        return True
    except Exception:
        logger.debug("daemon_available: schedd unreachable", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Schedd helpers
# ---------------------------------------------------------------------------


def get_schedd() -> htcondor.Schedd:
    """Return a Schedd handle to the local scheduler."""
    return htcondor.Schedd()


def _classad_to_dict(ad: Any) -> dict[str, Any]:
    """Convert a ClassAd object to a plain Python dict."""
    result: dict[str, Any] = {}
    for key in ad.keys():
        try:
            val = ad[key]
            # Convert ClassAd expressions to their evaluated form
            if hasattr(val, "eval"):
                val = val.eval()
            result[key] = val
        except Exception:
            result[key] = str(ad.lookup(key)) if hasattr(ad, "lookup") else None
    return result


# ---------------------------------------------------------------------------
# Job queries with caching
# ---------------------------------------------------------------------------


def _run_with_timeout(func, timeout: int = SCHEDD_QUERY_TIMEOUT):
    """Run a callable in a background thread with a timeout.

    Args:
        func: Zero-argument callable to execute.
        timeout: Maximum seconds to wait.

    Returns:
        The return value of *func*.

    Raises:
        TimeoutError: If *func* does not complete within *timeout* seconds.
        Exception: Any exception raised by *func*.
    """
    future = _schedd_executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        logger.error("Schedd query timed out after %ds", timeout)
        raise
    except Exception:
        logger.error("Schedd query failed", exc_info=True)
        raise


def query_jobs(
    constraint: str = DEFAULT_CONSTRAINT,
    projection: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Query active jobs from the schedd.

    Results are cached for 5 seconds to avoid hammering the schedd
    on rapid page loads / auto-refresh.

    A 15-second timeout is applied to prevent hanging on unresponsive daemons.

    Args:
        constraint: ClassAd expression to filter jobs.
        projection: List of attributes to return.

    Returns:
        List of job dicts.
    """
    proj = projection or DEFAULT_PROJECTION
    key = _cache_key("query_jobs", constraint, tuple(proj) if proj else None)

    if key in _query_cache:
        return _query_cache[key]

    schedd = get_schedd()

    def _do_query():
        return schedd.query(constraint=constraint, projection=proj)

    ads = _run_with_timeout(_do_query)
    jobs = []
    for ad in ads:
        d = _classad_to_dict(ad)
        # Add human-readable status
        status_code = d.get("JobStatus")
        d["JobStatusName"] = JOB_STATUS_MAP.get(status_code, f"Unknown({status_code})")
        jobs.append(d)

    _query_cache[key] = jobs
    return jobs


def query_history(
    constraint: str = DEFAULT_CONSTRAINT,
    projection: list[str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query completed jobs from the schedd history.

    Results are cached for 30 seconds since history data rarely changes.

    A 15-second timeout is applied to prevent hanging on unresponsive daemons.

    Args:
        constraint: ClassAd expression to filter jobs.
        projection: List of attributes to return.
        limit: Max number of results.

    Returns:
        List of job dicts.
    """
    proj = projection or DEFAULT_PROJECTION
    key = _cache_key("query_history", constraint, tuple(proj) if proj else None)

    if key in _history_cache:
        return _history_cache[key]

    schedd = get_schedd()
    try:
        def _do_history():
            return schedd.history(
                constraint=constraint,
                projection=proj,
                match=limit,
            )

        ads = _run_with_timeout(_do_history)
        jobs = []
        for ad in ads:
            d = _classad_to_dict(ad)
            status_code = d.get("JobStatus")
            d["JobStatusName"] = JOB_STATUS_MAP.get(
                status_code, f"Unknown({status_code})"
            )
            jobs.append(d)

        _history_cache[key] = jobs
        return jobs
    except TimeoutError:
        logger.error("History query timed out after %ds", SCHEDD_QUERY_TIMEOUT)
        return []
    except Exception as e:
        logger.error("Failed to query history: %s", e)
        return []


def get_job_status_counts() -> dict[str, int]:
    """Get aggregate counts of jobs by status.

    Only queries the JobStatus attribute for maximum performance.
    Results are cached for 5 seconds.

    Returns:
        Dict mapping status names to counts, plus a 'Total' key.
    """
    key = _cache_key("job_status_counts", DEFAULT_CONSTRAINT, None)

    if key in _counts_cache:
        return _counts_cache[key]

    # Only request JobStatus — much faster than full projection
    jobs = query_jobs(
        constraint=DEFAULT_CONSTRAINT,
        projection=["JobStatus"],
    )
    counts: dict[str, int] = {
        "Idle": 0,
        "Running": 0,
        "Held": 0,
        "Completed": 0,
        "Transferring Output": 0,
        "Suspended": 0,
        "Removed": 0,
        "Total": 0,
    }
    for job in jobs:
        status = job.get("JobStatusName", "Unknown")
        counts[status] = counts.get(status, 0) + 1
        counts["Total"] += 1

    _counts_cache[key] = counts
    return counts


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------


def submit_job(
    submit_dict: dict[str, str],
    count: int = 1,
    itemdata: list[dict[str, str]] | None = None,
    log_dir: str | None = None,
) -> int:
    """Submit a job to the local schedd.

    Args:
        submit_dict: Dictionary of submit description key-value pairs.
        count: Number of procs to queue.
        itemdata: Optional list of dicts for queue-from-list (each dict
                  is a set of variable assignments for one proc).
        log_dir: Optional path to a directory where logs, stdout, and stderr will be stored.

    Returns:
        The ClusterId of the submitted job.
    """
    sub_dict = dict(submit_dict)
    if log_dir:
        sub_dict["LogsDir"] = log_dir

    sub = htcondor.Submit(sub_dict)
    schedd = get_schedd()
    if itemdata:
        result = schedd.submit(sub, itemdata=iter(itemdata))
    else:
        result = schedd.submit(sub, count=count)
    cluster_id = result.cluster()
    logger.info("Submitted cluster %d (%d procs)", cluster_id, count)

    # Invalidate cache so subsequent queries see the new job immediately
    clear_cache()

    return cluster_id


def submit_from_file(file_content: str, log_dir: str | None = None) -> tuple[int, int]:
    """Submit a job from raw submit file content.

    Args:
        file_content: The text content of a .sub file.
        log_dir: Optional path to a directory where logs, stdout, and stderr will be stored.

    Returns:
        Tuple of (cluster_id, num_procs).
    """
    sub = htcondor.Submit(file_content)
    if log_dir:
        sub["LogsDir"] = log_dir

    schedd = get_schedd()
    result = schedd.submit(sub)
    cluster_id = result.cluster()
    num_procs = result.num_procs()
    logger.info(
        "Submitted cluster %d (%d procs) from file", cluster_id, num_procs
    )

    # Invalidate cache so subsequent queries see the new job immediately
    clear_cache()

    return cluster_id, num_procs


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


def qedit_job(cluster_id: int, proc_id: int, attr: str, value: str) -> dict[str, Any]:
    """Edit a ClassAd attribute on a job using condor_qedit.

    Args:
        cluster_id: The cluster ID of the job.
        proc_id: The proc ID of the job.
        attr: The attribute name to edit (e.g., 'request_disk').
        value: The new value for the attribute.

    Returns:
        Dict with qedit result details.
    """
    schedd = get_schedd()
    job_spec = f"{cluster_id}.{proc_id}"

    # Build a ClassAd with the attribute to edit
    ad = classad.ClassAd()
    ad[attr] = value

    # Use schedd.edit() to modify the job's attributes
    result = schedd.edit(job_spec, attr, value)
    logger.info("qedit %s: %s = %s → %s", job_spec, attr, value, result)

    # Invalidate cache so subsequent queries see the updated attributes
    clear_cache()

    return {
        "action": "qedit",
        "job_spec": job_spec,
        "attr": attr,
        "value": value,
        "result": str(result),
    }


def act_on_job(action: str, job_spec: str) -> dict[str, Any]:
    """Perform an action on a job or set of jobs.

    Args:
        action: One of 'hold', 'release', 'remove'.
        job_spec: Job ID like '123.0' or constraint like 'ClusterId == 123'.

    Returns:
        Dict with action result details.
    """
    action_map = {
        "hold": htcondor.JobAction.Hold,
        "release": htcondor.JobAction.Release,
        "remove": htcondor.JobAction.Remove,
    }
    if action not in action_map:
        raise ValueError(f"Invalid action: {action}. Must be one of {list(action_map)}")

    schedd = get_schedd()
    result = schedd.act(action_map[action], job_spec)
    logger.info("Action '%s' on '%s': %s", action, job_spec, result)

    # Invalidate cache after job action so new state is visible
    clear_cache()

    return {
        "action": action,
        "job_spec": job_spec,
        "result": str(result),
    }


# ---------------------------------------------------------------------------
# Job log / file helpers
# ---------------------------------------------------------------------------


def get_job_file_content(file_path: str, tail: int = 500) -> str:
    """Safely reads the last N lines of a file path."""
    if not file_path or not Path(file_path).exists():
        return ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])
    except Exception as e:
        return f"Error reading file {file_path}: {e}"


def get_job_log_file_paths(cluster_id: int, proc_id: int = 0) -> dict[str, str]:
    """Retrieve log, stdout, and stderr file paths for a job."""
    paths = {"log": "", "out": "", "err": ""}
    # Try database first — lazy import to avoid circular dependency at module level
    try:
        from app.models import JobSubmission as _JobSubmission
        submission = _JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        if submission and submission.log_dir:
            log_dir = submission.log_dir
            paths["log"] = str(Path(log_dir) / f"job_{cluster_id}.log")
            paths["out"] = str(Path(log_dir) / f"job_{cluster_id}_{proc_id}.out")
            paths["err"] = str(Path(log_dir) / f"job_{cluster_id}_{proc_id}.err")
            if Path(paths["log"]).exists():
                return paths
    except Exception as e:
        logger.error("Error querying JobSubmission DB: %s", e)

    # Fallback to ClassAd query
    try:
        jobs = query_jobs(
            constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
            projection=["UserLog", "Out", "Err"],
        )
        if not jobs:
            jobs = query_history(
                constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
                projection=["UserLog", "Out", "Err"],
                limit=1,
            )
        if jobs:
            job = jobs[0]
            if "UserLog" in job:
                paths["log"] = job["UserLog"]
            if "Out" in job:
                paths["out"] = job["Out"]
            if "Err" in job:
                paths["err"] = job["Err"]
    except Exception as e:
        logger.error("Error querying ClassAds for log paths: %s", e)

    return paths


def get_job_log(cluster_id: int, proc_id: int = 0, tail: int = 200) -> str:
    """Try to read the job's log file using resolved paths."""
    paths = get_job_log_file_paths(cluster_id, proc_id)
    log_path = paths.get("log")
    if not log_path:
        return f"No log file path found for job {cluster_id}.{proc_id}"

    content = get_job_file_content(log_path, tail=tail)
    if not content:
        return f"Log file not found on disk or empty for job {cluster_id}.{proc_id} at {log_path}"
    return content