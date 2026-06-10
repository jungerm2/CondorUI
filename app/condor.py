"""Wrapper around htcondor Python bindings.

Tries to import htcondor2 (v25.x+) first, then falls back to htcondor (v1 API).
"""

from __future__ import annotations

import getpass
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default to only showing the current user's jobs for performance
CURRENT_USER = getpass.getuser()
DEFAULT_CONSTRAINT = f'Owner == "{CURRENT_USER}"'

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


def query_jobs(
    constraint: str = DEFAULT_CONSTRAINT,
    projection: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Query active jobs from the schedd.

    Args:
        constraint: ClassAd expression to filter jobs.
        projection: List of attributes to return.

    Returns:
        List of job dicts.
    """
    schedd = get_schedd()
    proj = projection or DEFAULT_PROJECTION
    ads = schedd.query(constraint=constraint, projection=proj)
    jobs = []
    for ad in ads:
        d = _classad_to_dict(ad)
        # Add human-readable status
        status_code = d.get("JobStatus")
        d["JobStatusName"] = JOB_STATUS_MAP.get(status_code, f"Unknown({status_code})")
        jobs.append(d)
    return jobs


def query_history(
    constraint: str = DEFAULT_CONSTRAINT,
    projection: list[str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query completed jobs from the schedd history.

    Args:
        constraint: ClassAd expression to filter jobs.
        projection: List of attributes to return.
        limit: Max number of results.

    Returns:
        List of job dicts.
    """
    schedd = get_schedd()
    proj = projection or DEFAULT_PROJECTION
    try:
        ads = schedd.history(
            constraint=constraint,
            projection=proj,
            match=limit,
        )
        jobs = []
        for ad in ads:
            d = _classad_to_dict(ad)
            status_code = d.get("JobStatus")
            d["JobStatusName"] = JOB_STATUS_MAP.get(
                status_code, f"Unknown({status_code})"
            )
            jobs.append(d)
        return jobs
    except Exception as e:
        logger.error("Failed to query history: %s", e)
        return []


def get_job_status_counts() -> dict[str, int]:
    """Get aggregate counts of jobs by status.

    Returns:
        Dict mapping status names to counts, plus a 'Total' key.
    """
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
    return counts


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
        import os
        sub_dict["output"] = os.path.join(log_dir, "job_$(ClusterId)_$(ProcId).out")
        sub_dict["error"] = os.path.join(log_dir, "job_$(ClusterId)_$(ProcId).err")
        sub_dict["log"] = os.path.join(log_dir, "job_$(ClusterId).log")

    sub = htcondor.Submit(sub_dict)
    schedd = get_schedd()
    if itemdata:
        result = schedd.submit(sub, itemdata=iter(itemdata))
    else:
        result = schedd.submit(sub, count=count)
    cluster_id = result.cluster()
    logger.info("Submitted cluster %d (%d procs)", cluster_id, count)
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
        import os
        sub["output"] = os.path.join(log_dir, "job_$(ClusterId)_$(ProcId).out")
        sub["error"] = os.path.join(log_dir, "job_$(ClusterId)_$(ProcId).err")
        sub["log"] = os.path.join(log_dir, "job_$(ClusterId).log")

    schedd = get_schedd()
    result = schedd.submit(sub)
    cluster_id = result.cluster()
    num_procs = result.num_procs()
    logger.info(
        "Submitted cluster %d (%d procs) from file", cluster_id, num_procs
    )
    return cluster_id, num_procs


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
    return {
        "action": action,
        "job_spec": job_spec,
        "result": str(result),
    }


def get_job_file_content(file_path: str, tail: int = 500) -> str:
    """Safely reads the last N lines of a file path."""
    import os
    if not file_path or not os.path.exists(file_path):
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
    # Try database first
    try:
        from app.models import JobSubmission
        submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        if submission and submission.log_dir:
            import os
            log_dir = submission.log_dir
            paths["log"] = os.path.join(log_dir, f"job_{cluster_id}.log")
            paths["out"] = os.path.join(log_dir, f"job_{cluster_id}_{proc_id}.out")
            paths["err"] = os.path.join(log_dir, f"job_{cluster_id}_{proc_id}.err")
            if os.path.exists(paths["log"]):
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
