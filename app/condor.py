"""Wrapper around htcondor Python bindings.

Tries to import htcondor2 (v25.x+) first, then falls back to htcondor (v1 API).
"""

from __future__ import annotations

import getpass
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Upper bound on how many bytes of a log/output file we read when tailing
MAX_TAIL_BYTES = 256 * 1024

# Default to only showing the current user's jobs for performance
CURRENT_USER = getpass.getuser()
DEFAULT_CONSTRAINT = f'Owner == "{CURRENT_USER}"'

# Timeout for schedd queries (seconds) — prevents hanging on unresponsive daemons
SCHEDD_QUERY_TIMEOUT = 15

# Memoized daemon probe: success expires faster than failure because a flaky
# schedd should get re-probed sooner than every full-availability window
_DAEMON_PROBE_TTL = 5.0
_DAEMON_FAIL_TTL = 10.0
_daemon_probe: tuple[float, bool] | None = None
_daemon_probe_lock = Lock()

# Shared thread pool for running schedd queries with a timeout.
# Mutable via _retire_schedd_pool: Python threads cannot be killed, so a
# query wedged inside htcondor's C bindings would keep its worker forever;
# swapping in a fresh executor after timeouts restores query capacity.
_schedd_executor = ThreadPoolExecutor(max_workers=4)


class _CondorMutex:
    """Mutual exclusion over htcondor's C calls, with caller-side abandon.

    Permit counting is the wrong model here: a call that timed out cannot
    know whether its abandoned worker still holds the mutex, so neither
    under- nor over-release is detectable.  Ownership is instead a single
    token: only the gate's current holder can free it (a stale worker's
    late release is a no-op), and ``force_release`` drops ownership
    regardless, idempotently.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._owner: object | None = None

    def acquire(self) -> object:
        with self._cond:
            while self._owner is not None:
                self._cond.wait()
            self._owner = owner = object()
            return owner

    def release(self, token: object) -> None:
        """Release the gate only if *token* still owns it."""
        with self._cond:
            if self._owner is token:
                self._owner = None
                self._cond.notify()

    def force_release(self) -> None:
        """Open the gate unconditionally; safe to call at any time."""
        with self._cond:
            self._owner = None
            self._cond.notify()


_condor_serial_lock = _CondorMutex()


@contextmanager
def _condor_guard():
    """Run htcondor calls under the serialization mutex."""
    token = _condor_serial_lock.acquire()
    try:
        yield
    finally:
        _condor_serial_lock.release(token)


# --- Attempt to import the HTCondor bindings ---
try:
    import classad2 as classad
    import htcondor2 as htcondor

    logger.info("Using htcondor2 (v2 API)")
except ImportError:
    import classad  # type: ignore[no-redef]  # noqa: F401
    import htcondor  # type: ignore[no-redef]

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
    "RequestGPUs",
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
    "LastRemoteWallClockTime",
    "CumulativeSuspensionTime",
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
    global _daemon_probe
    with _daemon_probe_lock:
        _daemon_probe = None


# ---------------------------------------------------------------------------
# Daemon availability check
# ---------------------------------------------------------------------------


def daemon_available() -> bool:
    """Quick check if the HTCondor scheduler daemon (schedd) is reachable.

    Tries a lightweight ``schedd.query(limit=1)`` with a short timeout and
    returns ``True`` if it succeeds.  If the daemon is unreachable or the
    Python bindings are not installed, returns ``False``.

    The result is memoized for a few seconds — this is called at the top
    of most API endpoints, so probing the schedd every time would defeat
    the query caches.

    The caller should **not** rely on this as a gate — the rest of the API
    gracefully returns empty results when the daemon is unavailable.
    """
    global _daemon_probe
    now = time.monotonic()
    with _daemon_probe_lock:
        if _daemon_probe is not None and _daemon_probe[0] > now:
            return _daemon_probe[1]

    available = False
    try:
        schedd = get_schedd()
        _run_with_timeout(
            lambda: schedd.query(
                constraint="JobStatus == 1", projection=["ClusterId"], limit=1
            ),
            timeout=5,  # liveness probe — shorter than full query timeout
        )
        available = True
    except Exception:
        logger.debug("daemon_available: schedd unreachable", exc_info=True)

    ttl = _DAEMON_PROBE_TTL if available else _DAEMON_FAIL_TTL
    with _daemon_probe_lock:
        _daemon_probe = (time.monotonic() + ttl, available)
    return available


# ---------------------------------------------------------------------------
# Schedd helpers
# ---------------------------------------------------------------------------


def get_schedd() -> htcondor.Schedd:
    """Return a Schedd handle to the local scheduler."""
    return htcondor.Schedd()


def _classad_to_dict(ad: Any) -> dict[str, Any]:
    """Convert a ClassAd object to a plain Python dict."""
    result: dict[str, Any] = {}
    for key in ad:
        try:
            val = ad[key]
            # Convert ClassAd expressions to their evaluated form
            if hasattr(val, "eval"):
                val = val.eval()
            result[key] = val
        except Exception:  # noqa: BLE001
            result[key] = str(ad.lookup(key)) if hasattr(ad, "lookup") else None
    return result


# ---------------------------------------------------------------------------
# Job queries with caching
# ---------------------------------------------------------------------------


def _retire_schedd_pool() -> None:
    """Discard the schedd query pool after a timeout and start a fresh one.

    ``future.result(timeout=...)`` cannot cancel a query that is already
    running: the worker stays blocked inside htcondor's C bindings for as
    long as the daemon connection takes to give up.  With a small pool, a
    handful of wedged queries then cascade — every later pagination, probe,
    and history scan times out at 15s even after the schedd recovers.
    Retiring the pool restores capacity immediately; the abandoned worker
    leaks (bounded by the number of timeouts) instead of poisoning the app.

    In-flight queries keep finishing in the old pool's threads and their
    callers still receive their results; only queued-but-unstarted work is
    cancelled, which the submit-time retry handles.
    """
    global _schedd_executor
    pool, _schedd_executor = _schedd_executor, ThreadPoolExecutor(max_workers=4)
    pool.shutdown(wait=False, cancel_futures=True)
    logger.warning("Retired schedd query pool after a timed-out query")


def _run_with_timeout(func, timeout: int = SCHEDD_QUERY_TIMEOUT):
    """Run *func* on the schedd thread pool with a timeout.

    Raises:
        TimeoutError: If *func* does not complete within *timeout* seconds.
        Exception: Any exception raised by *func*.
    """

    def _serialized():
        with _condor_guard():
            return func()

    # Retiring replaces the global atomically; a submit can only lose the
    # race by targeting a pool that just shut down, and one retry lands on
    # the replacement.
    try:
        future = _schedd_executor.submit(_serialized)
    except RuntimeError:
        future = _schedd_executor.submit(_serialized)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        logger.error("Schedd query timed out after %ds", timeout)
        _retire_schedd_pool()
        # The abandoned worker may stay blocked forever while holding the
        # serialization mutex; force the permit back open so later calls
        # are not poisoned.
        _condor_serial_lock.force_release()
        raise
    except Exception:
        logger.exception("Schedd query failed")
        raise


def _process_classad_list(ads: list) -> list[dict[str, Any]]:
    """Convert a list of ClassAd objects to plain dicts with human-readable status."""
    jobs = []
    for ad in ads:
        d = _classad_to_dict(ad)
        status_code = d.get("JobStatus", -1)
        d["JobStatusName"] = JOB_STATUS_MAP.get(status_code, f"Unknown({status_code})")
        jobs.append(d)
    return jobs


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
    jobs = _process_classad_list(ads)

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

    try:
        schedd = get_schedd()
        ads = _run_with_timeout(
            lambda: schedd.history(
                constraint=constraint,
                projection=proj,
                match=limit,
            )
        )
        jobs = _process_classad_list(ads)

        _history_cache[key] = jobs
        return jobs
    except TimeoutError:
        logger.error("History query timed out after %ds", SCHEDD_QUERY_TIMEOUT)
        return []
    except Exception as e:  # noqa: BLE001
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


def _resolve_output_path(job: dict[str, Any]) -> str | None:
    """Return the resolved output directory for one job ClassAd.

    Accepts ``output_destination`` (URL or path) or ``output_directory``
    (submit-side path) — HTCondor permits only one of the two.  The outputs
    page lists whatever files exist in this resolved directory.
    """
    return job.get("output_destination") or job.get("output_directory")


def _record_submission(
    submit_source: dict[str, str] | str, cluster_id: int, num_procs: int, name: str
) -> None:
    """Query resolved output paths for *cluster_id* and store the JobSubmission record.

    *submit_source* is the submit dict for API-based submits, or the raw
    .sub file text for file-based submits.

    The output path resolves from ``output_destination`` or equivalently
    ``output_directory`` (a plain submit-side path; HTCondor allows only one
    of the two).  The outputs page lists files from this resolved directory.
    """
    log_path = None
    out_path = None
    err_path = None
    output_destination = None
    transfer_output_remaps = None
    try:
        jobs = query_jobs(
            constraint=f"ClusterId == {cluster_id} && ProcId == 0",
            projection=[
                "UserLog",
                "Out",
                "Err",
                "output_destination",
                "output_directory",
                "transfer_output_remaps",
            ],
        )
        if jobs:
            job = jobs[0]
            log_path = job.get("UserLog")
            out_path = job.get("Out")
            err_path = job.get("Err")
            output_destination = _resolve_output_path(job)
            transfer_output_remaps = job.get("transfer_output_remaps")
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to query ClassAd for cluster %d after submit", cluster_id
        )

    if isinstance(submit_source, dict):
        description = json.dumps(submit_source)
        cmd = submit_source.get("executable", submit_source.get("shell", ""))
    else:
        description = submit_source
        cmd = ""
        for line in submit_source.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("executable") and "=" in stripped:
                cmd = stripped.split("=", 1)[1].strip()
                break

    from app import db
    from app.models import JobSubmission

    submission = JobSubmission(
        cluster_id=cluster_id,
        name=name,
        submit_description=description,
        num_procs=num_procs,
        log_path=log_path,
        out_path=out_path,
        err_path=err_path,
        output_destination=output_destination,
        transfer_output_remaps=transfer_output_remaps,
        owner=getpass.getuser(),
        cmd=cmd,
    )
    db.session.add(submission)
    db.session.commit()

    # Invalidate cache so subsequent queries see the new job immediately
    clear_cache()


def submit_job(
    submit_dict: dict[str, str],
    count: int = 1,
    itemdata: list[dict[str, str]] | None = None,
    name: str = "Untitled Job",
    queue_stmt: str | None = None,
) -> tuple[int, int]:
    """Submit a job to the local schedd.

    Sets ``LogsDir`` / ``OutputsDir`` on the submit description to the
    configured base directories.  HTCondor will create per-cluster
    subdirectories automatically when writing log/out/err files.
    Also creates a :class:`JobSubmission` record in the local database.

    Args:
        submit_dict: Dictionary of submit description key-value pairs.
        count: Number of procs to queue.
        itemdata: Optional list of dicts for queue-from-list (each dict
                  is a set of variable assignments for one proc).
        name: Display name for the submission record.
        queue_stmt: Optional queue statement string (e.g., "1", "matching ...").
                    If provided, passed as the ``queue`` parameter to
                    ``htcondor.Submit()`` instead of being in the dict.

    Returns:
        Tuple of (cluster_id, num_procs).
    """
    from flask import current_app

    sub_dict = dict(submit_dict)
    sub_dict["LogsDir"] = str(current_app.config["JOB_LOGS_DIR"])
    sub_dict["OutputsDir"] = str(current_app.config["OUTPUT_DIR"])

    if queue_stmt is not None:
        sub = htcondor.Submit(sub_dict, queue=queue_stmt)
    else:
        sub = htcondor.Submit(sub_dict)
    schedd = get_schedd()
    with _condor_guard():
        if itemdata:
            result = schedd.submit(sub, itemdata=iter(itemdata))
            num_procs = len(itemdata)
        else:
            if queue_stmt is not None:
                # queue statement already contains the count, don't pass it again
                result = schedd.submit(sub)
                num_procs = result.num_procs()
            else:
                result = schedd.submit(sub, count=count)
                num_procs = count
    cluster_id = result.cluster()
    logger.info("Submitted cluster %d (%d procs)", cluster_id, num_procs)

    _record_submission(submit_dict, cluster_id, num_procs, name)
    return cluster_id, num_procs


def submit_from_file(
    file_content: str,
    name: str = "Untitled Job",
) -> tuple[int, int]:
    """Submit a job from raw submit file content.

    Sets ``LogsDir`` / ``OutputsDir`` on the submit description to the
    configured base directories.  HTCondor will create per-cluster
    subdirectories automatically when writing log/out/err files.
    Also creates a :class:`JobSubmission` record in the local database.

    Args:
        file_content: The text content of a .sub file.
        name: Display name for the submission record.

    Returns:
        Tuple of (cluster_id, num_procs).
    """
    from flask import current_app

    sub = htcondor.Submit(file_content)
    sub["LogsDir"] = str(current_app.config["JOB_LOGS_DIR"])
    sub["OutputsDir"] = str(current_app.config["OUTPUT_DIR"])

    schedd = get_schedd()
    with _condor_guard():
        result = schedd.submit(sub)
    cluster_id = result.cluster()
    num_procs = result.num_procs()
    logger.info("Submitted cluster %d (%d procs) from file", cluster_id, num_procs)

    _record_submission(file_content, cluster_id, num_procs, name)
    return cluster_id, num_procs


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


def _classad_edit_value(value: str) -> str:
    """Quote a qedit value for schedd.edit unless it's already a valid expression.

    HTCondor evaluates the value as a ClassAd expression: numbers, quoted
    strings, and keywords (True/False/UNDEFINED) pass through, while plain
    text like "disk full" needs wrapping in double quotes to parse.
    """
    s = str(value).strip()
    if not s or (s.startswith('"') and s.endswith('"') and len(s) >= 2):
        return s
    if s.lower() in ("true", "false", "undefined", "defined"):
        return s
    try:
        float(s)
        return s
    except ValueError:
        return f'"{s}"'


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

    # schedd.edit() evaluates the value as a ClassAd expression, so plain
    # string values must be quoted to survive parsing (e.g. hold reasons).
    edit_value = _classad_edit_value(value)

    # Use schedd.edit() to modify the job's attributes
    with _condor_guard():
        result = schedd.edit(job_spec, attr, edit_value)
    logger.info("qedit %s: %s = %s → %s", job_spec, attr, edit_value, result)

    # Invalidate cache so subsequent queries see the updated attributes
    clear_cache()

    return {
        "action": "qedit",
        "job_spec": job_spec,
        "attr": attr,
        "value": edit_value,
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
    with _condor_guard():
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
    """Safely reads the last N lines of a file path.

    Reads backward from the end of the file in a single bounded chunk
    (at most ``MAX_TAIL_BYTES``) so huge job logs never get fully loaded
    into memory.
    """
    if not file_path or not Path(file_path).exists():
        return ""
    try:
        with open(file_path, "rb") as f:
            f.seek(0, 2)  # SEEK_END
            size = f.tell()
            read_bytes = min(size, MAX_TAIL_BYTES)
            f.seek(size - read_bytes)
            chunk = f.read(read_bytes)

        text = chunk.decode("utf-8", errors="replace")
        # If we only read a suffix of the file, the first line may be
        # truncated mid-line — drop it unless the file has no newlines.
        if read_bytes < size and "\n" in text:
            text = text.split("\n", 1)[1]

        lines = text.splitlines(keepends=True)
        return "".join(lines[-tail:])
    except Exception as e:  # noqa: BLE001
        logger.warning("Error reading file %s: %s", file_path, e)
        return f"Error reading file {file_path}"


def get_job_log_file_paths(cluster_id: int, proc_id: int = 0) -> dict[str, str]:
    """Retrieve log, stdout, and stderr file paths for a job.

    Priority:
    1. DB stored paths (``log_path``, ``out_path``, ``err_path``) — for jobs
       submitted through the web UI after the schema change.
    2. ClassAd query — for jobs not in the DB or old records without stored paths.
    3. For non-zero procs, derive per-proc out/err paths from the stored
       ProcId-0 path by swapping the zero-padded proc component.

    The DB record only stores ProcId-0 paths, so querying it directly for
    proc N would silently return proc 0's stdout/stderr when files follow a
    per-proc template (e.g. ``.../$INT(ProcId,%05d).out``).
    """
    paths = {"log": "", "out": "", "err": ""}
    # Try database first — lazy import to avoid circular dependency at module level
    db_out_path = None
    db_err_path = None
    try:
        from app.models import JobSubmission as _JobSubmission

        submission = _JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        if submission:
            if submission.log_path:
                paths["log"] = submission.log_path
            if submission.out_path:
                paths["out"] = submission.out_path
                db_out_path = submission.out_path
            if submission.err_path:
                paths["err"] = submission.err_path
                db_err_path = submission.err_path
    except Exception as e:  # noqa: BLE001
        logger.error("Error querying JobSubmission DB: %s", e)

    # Proc 0 is exactly what the DB stores, and its UserLog is the shared
    # cluster log — no ClassAd query needed when it exists on disk.
    if proc_id == 0 and paths["log"] and Path(paths["log"]).exists():
        return paths

    # ClassAd query — resolves exact per-proc paths and covers jobs missing
    # from the DB entirely. Queued jobs come from query_jobs, finished ones
    # from query_history. On failure the ClassAd candidates stay None and
    # _pick_per_proc_path derives from the DB's proc-0 record.
    classad_out = classad_err = None
    try:
        constraint = f"ClusterId == {cluster_id} && ProcId == {proc_id}"
        jobs = query_jobs(
            constraint=constraint,
            projection=["UserLog", "Out", "Err"],
        )
        if not jobs:
            jobs = query_history(
                constraint=constraint,
                projection=["UserLog", "Out", "Err"],
                limit=1,
            )
        if jobs:
            job = jobs[0]
            if "UserLog" in job:
                paths["log"] = job["UserLog"]
            classad_out = job.get("Out")
            classad_err = job.get("Err")
    except Exception as e:  # noqa: BLE001
        logger.error("Error querying ClassAds for log paths: %s", e)

    if proc_id != 0:
        paths["out"] = _pick_per_proc_path(db_out_path, classad_out, proc_id)
        paths["err"] = _pick_per_proc_path(db_err_path, classad_err, proc_id)
    else:
        if classad_out is not None and not paths["out"]:
            paths["out"] = str(classad_out)
        if classad_err is not None and not paths["err"]:
            paths["err"] = str(classad_err)

    return paths


def _path_with_proc(path: str, proc_id: int) -> str:
    """Swap the zero-padded ProcId component (resolved from a ProcId-0 path).

    HTCondor resolves ``$INT(ProcId,%0Nd)``-style templates at write time, so
    the stored ProcId-0 path contains runs of leading zeros for the proc id.
    Replacing every zero-run in the *filename* (not touched elsewhere) that is
    not directly attached to another digit with the zero-padded requested proc
    reproduces the per-proc filename (``.../1234.0.out`` → ``.../1234.5.out``,
    ``.../00000.log`` → ``.../00005.log``), while leaving 8-digit cluster ids
    like ``00001234`` untouched (their zero-run runs into a non-zero digit).
    Directory components are never modified — only the filename can carry the
    ProcId substitution safely.
    """
    if not path:
        return path

    def _swap(match: re.Match) -> str:
        return str(proc_id).zfill(len(match.group(0)))

    filename = Path(path).name
    if not re.search(r"(?<!\d)0+(?!\d)", filename):
        return path
    # Zero-run in the filename: not followed by another digit, not preceded
    # by another digit
    new_name = re.sub(r"(?<!\d)0+(?!\d)", _swap, filename)
    if not new_name or new_name in (".", ".."):
        return path
    return str(Path(path).with_name(new_name))


def _pick_per_proc_path(
    proc0_path: str | None, classad_path: str | None, proc_id: int
) -> str:
    """Choose the best per-proc stdout/stderr path.

    Preference order (existing files always win over guesses):
    1. The derived per-proc path if that file exists on disk.
    2. The stored proc-0/ClassAd path when that file exists — covers
       clusters that share one Out/Err file across procs.
    3. The ClassAd-provided path when it looks fully resolved (no $(...)).
    4. Whatever non-empty path is available.
    """
    if proc0_path:
        derived = _path_with_proc(proc0_path, proc_id)
        if derived and derived != proc0_path and Path(derived).exists():
            return derived
    if proc0_path and Path(proc0_path).exists():
        return proc0_path
    if classad_path and "$(" not in classad_path:
        return str(classad_path)
    if classad_path and Path(str(classad_path)).exists():
        return str(classad_path)
    return proc0_path or (str(classad_path) if classad_path else "")


def get_job_log(cluster_id: int, proc_id: int = 0, tail: int = 200) -> str:
    """Try to read the job's log file using resolved paths."""
    paths = get_job_log_file_paths(cluster_id, proc_id)
    log_path = paths.get("log")
    if not log_path:
        return f"No log file path found for job {cluster_id}.{proc_id}"

    content = get_job_file_content(log_path, tail=tail)
    if not content:
        return f"Log file not found on disk or empty for job {cluster_id}.{proc_id} at {log_path}"
    return filter_job_log_events(content, cluster_id, proc_id)


# UserLog event header, e.g. "000 (1234.000.000) 02/10 14:22:01 ..."
_EVENT_HEADER_RE = re.compile(r"^\d{3}\s*\((\d+)\.(\d+)\.(\d+)\)")


def filter_job_log_events(content: str, cluster_id: int, proc_id: int = 0) -> str:
    """Keep only the UserLog events belonging to the requested job.

    A submit description's ``Log`` file may be shared by every proc of the
    cluster (or, when it doesn't include ``$(ClusterId)``, even by several
    clusters), so a per-proc view otherwise shows events from other jobs.
    HTCondor events always start with a ``NNN (cluster.proc.subproc)``
    header; each event is headed by that line and may have detail lines
    after it. If no event explicitly for the requested proc exists, all
    events of the cluster are kept (cluster-wide view).
    """
    if not content:
        return content

    blocks: list[tuple[tuple[int, int] | None, list[str]]] = []
    event: tuple[int, int] | None = None
    lines: list[str] = []
    for line in content.splitlines(keepends=True):
        m = _EVENT_HEADER_RE.match(line)
        if m:
            if lines:
                blocks.append((event, lines))
            event = (int(m.group(1)), int(m.group(2)))
            lines = [line]
        else:
            lines.append(line)
    if lines:
        blocks.append((event, lines))

    has_proc_events = any(ev == (cluster_id, proc_id) for ev, _ in blocks)
    kept: list[str] = []
    for ev, block_lines in blocks:
        if ev is None:
            # Preamble before the first event header (rare) — drop it when
            # we're filtering, it can't be attributed to any job.
            continue
        cluster, proc = ev
        if cluster != cluster_id:
            continue
        if has_proc_events and proc != proc_id:
            continue
        kept.extend(block_lines)
    if not kept:
        return content  # Unparseable/foreign format — don't erase data
    return "".join(kept)


# ---------------------------------------------------------------------------
# Completion facts from UserLogs
# ---------------------------------------------------------------------------

# A finished job's UserLog survives even after the schedd history has rolled
# over, and reading it is local I/O.  The dashboard used to get these fields
# from a constrained schedd.history scan on every load; that scan walked the
# whole history file and could exceed the query timeout (fe35348).
MAX_COMPLETION_LOG_BYTES = 64 * 1024 * 1024
_EVENT_TERMINATOR_RE = re.compile(rb"(?m)^\.\.\.[ \t\r]*$")

# Finished logs are immutable, so cache by path/size/mtime.  A changed file
# gets a new key and the old entry ages out.
_completion_cache: TTLCache = TTLCache(maxsize=256, ttl=3600.0)
_completion_cache_lock = Lock()


def read_job_log_completions(log_path: str) -> dict[tuple[int, int], dict]:
    """Extract completion facts from an HTCondor UserLog.

    Returns ``{(ClusterId, ProcId): fields}`` with ``CompletionDate`` and,
    when the log contains the matching execute event, wall-clock and exit
    fields.  Wall time is the sum of execute→terminate/evict intervals;
    suspension is reported separately because the dashboard subtracts
    ``CumulativeSuspensionTime``.

    ``JobEventLog`` handles the event format and year-less timestamps.  We
    stop after the number of complete events counted in the file so an
    unfinished tail of a live log never makes the reader wait for more.
    """
    if not log_path:
        return {}
    try:
        stat = Path(log_path).stat()
    except OSError:
        return {}
    if stat.st_size == 0:
        return {}
    if stat.st_size > MAX_COMPLETION_LOG_BYTES:
        logger.warning("Skipping oversized job log for completion data: %s", log_path)
        return {}

    key = (str(log_path), stat.st_size, stat.st_mtime_ns)
    with _completion_cache_lock:
        cached = _completion_cache.get(key)
    if cached is not None:
        return cached

    try:
        # Every complete event ends with a line containing just "...".
        # Counting terminators lets us read exactly that many events: at EOF
        # JobEventLog waits for appended events (up to its deadline), and a
        # partial trailing event would otherwise stall this request.
        data = Path(log_path).read_bytes()
        event_count = len(_EVENT_TERMINATOR_RE.findall(data))
        completions = (
            _parse_completion_events(log_path, event_count) if event_count else {}
        )
    except Exception:
        logger.warning(
            "Could not parse job log for completion data: %s", log_path, exc_info=True
        )
        completions = {}

    with _completion_cache_lock:
        _completion_cache[key] = completions
    return completions


def _parse_completion_events(
    log_path: str, event_count: int
) -> dict[tuple[int, int], dict]:
    """Walk the complete events in *log_path* and keep termination facts."""
    runs: dict[tuple[int, int], dict] = {}
    log = htcondor.JobEventLog(log_path)
    try:
        events = log.events(1)
        for _ in range(event_count):
            try:
                event = next(events)
            except StopIteration:
                break
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Stopped reading job log at a malformed event: %s", log_path
                )
                break

            cluster, proc = int(event.cluster), int(event.proc)
            if cluster < 0 or proc < 0:
                continue  # cluster-wide events have no proc id
            state = runs.setdefault(
                (cluster, proc),
                {
                    "run_start": None,
                    "suspended_at": None,
                    "wall": 0.0,
                    "suspension": 0.0,
                    "completion": None,
                    "exit_code": None,
                    "by_signal": None,
                },
            )
            event_type = int(event.type)
            timestamp = int(event.timestamp)
            if event_type == 1:  # JOB_EXECUTE
                state["run_start"] = timestamp
            elif event_type == 10:  # JOB_SUSPENDED
                state["suspended_at"] = timestamp
            elif event_type == 11:  # JOB_UNSUSPENDED
                if state["suspended_at"] is not None:
                    state["suspension"] += max(0, timestamp - state["suspended_at"])
                    state["suspended_at"] = None
            elif event_type in (4, 5, 9):  # EVICTED, TERMINATED, ABORTED
                _close_log_run(state, timestamp)
                if event_type in (5, 9):
                    state["completion"] = timestamp
                    normal = event.get("TerminatedNormally")
                    return_value = event.get("ReturnValue")
                    if normal is not None:
                        state["by_signal"] = not bool(normal)
                        if return_value is not None:
                            state["exit_code"] = int(return_value)
    finally:
        try:
            log.close()
        except Exception:
            logger.debug("Error closing job event log: %s", log_path, exc_info=True)

    result: dict[tuple[int, int], dict] = {}
    for key, state in runs.items():
        if state["completion"] is None:
            continue
        entry: dict = {"CompletionDate": int(state["completion"])}
        wall = round(state["wall"])
        if wall > 0:
            entry["RemoteWallClockTime"] = wall
            entry["LastRemoteWallClockTime"] = wall
        suspension = round(state["suspension"])
        if suspension > 0:
            entry["CumulativeSuspensionTime"] = suspension
        if state["exit_code"] is not None:
            entry["ExitCode"] = int(state["exit_code"])
        if state["by_signal"] is not None:
            entry["ExitBySignal"] = bool(state["by_signal"])
        result[key] = entry
    return result


def _close_log_run(state: dict, timestamp: int) -> None:
    """Close an open execution interval and any suspension at *timestamp*."""
    if state["run_start"] is not None:
        state["wall"] += max(0, timestamp - state["run_start"])
        state["run_start"] = None
    if state["suspended_at"] is not None:
        state["suspension"] += max(0, timestamp - state["suspended_at"])
        state["suspended_at"] = None
