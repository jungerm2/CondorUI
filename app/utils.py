"""Shared utility functions for the Condor Web UI."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from flask import current_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job directory helpers
# ---------------------------------------------------------------------------


def generate_job_uuid() -> str:
    """Generate a unique job UUID string like 'job_<hex>'."""
    return f"job_{uuid.uuid4().hex}"


def create_job_directories(
    log_dir_base: str | None = None,
    output_dir_base: str | None = None,
) -> tuple[Path, Path]:
    """Create per-job log and output directories.

    Creates directories under JOB_LOGS_DIR and OUTPUT_DIR with a unique
    job UUID.  Returns the (log_dir, output_dir) paths as resolved
    ``Path`` objects.

    Args:
        log_dir_base: Override for JOB_LOGS_DIR (defaults to config).
        output_dir_base: Override for OUTPUT_DIR (defaults to config).

    Returns:
        Tuple of (log_dir_path, output_dir_path) resolved Path objects.
    """

    job_uuid = generate_job_uuid()
    log_dir_base = log_dir_base or str(current_app.config["JOB_LOGS_DIR"])
    output_dir_base = output_dir_base or str(current_app.config["OUTPUT_DIR"])

    log_dir_path = Path(log_dir_base) / job_uuid
    log_dir_path.mkdir(parents=True, exist_ok=True)

    output_dir_path = Path(output_dir_base) / job_uuid
    output_dir_path.mkdir(parents=True, exist_ok=True)

    return log_dir_path.resolve(), output_dir_path.resolve()


# ---------------------------------------------------------------------------
# Shell command resolution
# ---------------------------------------------------------------------------


def resolve_shell_commands(jobs: list[dict]) -> None:
    """Resolve /bin/sh commands to the original shell command from the DB.

    For any job in the list with Cmd == "/bin/sh", look up the submission
    record in the local database and replace Cmd with the original shell
    command (e.g., "ls -al") stored in the submit_description.

    Modifies the list in-place.
    """
    from app.models import JobSubmission

    shell_job_ids = [j.get("ClusterId") for j in jobs if j.get("Cmd") == "/bin/sh"]
    if not shell_job_ids:
        return

    submissions = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(shell_job_ids)
    ).all()
    sub_map = {s.cluster_id: s for s in submissions}

    for job in jobs:
        if job.get("Cmd") != "/bin/sh":
            continue
        sub = sub_map.get(job.get("ClusterId"))
        if not sub:
            continue
        try:
            desc = sub.submit_description
            if desc and desc.strip().startswith("{"):
                parsed = json.loads(desc)
                shell_cmd = parsed.get("shell", "")
                if shell_cmd:
                    job["Cmd"] = shell_cmd
                    job["Args"] = ""
        except json.JSONDecodeError, AttributeError:
            pass


# ---------------------------------------------------------------------------
# File upload helpers
# ---------------------------------------------------------------------------


def save_uploaded_stream(
    stream, dest_dir: str, original_filename: str, name: str | None = None
) -> tuple[str, int]:
    """Stream a raw uploaded file to disk with a unique name.

    Args:
        stream: A file-like object to read from (e.g. request.stream).
        dest_dir: Directory to save the file into.
        original_filename: The original filename for extension detection.
        name: Optional display name (used for the safe filename base).
              Falls back to original filename without extension.

    Returns:
        (unique_name, size) tuple.
    """
    dest_path_obj = Path(dest_dir)
    dest_path_obj.mkdir(parents=True, exist_ok=True)

    # Create UUID directory structure: dest_dir/uuid/
    file_uuid = uuid.uuid4().hex
    subdir = dest_path_obj / file_uuid
    subdir.mkdir(parents=True, exist_ok=True)

    # Save with original filename: dest_dir/uuid/original_filename
    dest_path = subdir / original_filename
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(stream, f, length=1024 * 1024)

    # Return the relative unique name (uuid/original_filename)
    rel_name = f"{file_uuid}/{original_filename}"
    size = dest_path.stat().st_size
    return rel_name, size


def make_uuid_filename(dest_dir: str, original_filename: str) -> str:
    """Generate a UUID-based relative filename in the format uuid/original.

    Args:
        dest_dir: Base directory for the file.
        original_filename: The original filename to use.

    Returns:
        Relative path string like 'abc123/file.txt'.
    """
    file_uuid = uuid.uuid4().hex
    return f"{file_uuid}/{original_filename}"


# ---------------------------------------------------------------------------
# History job builder
# ---------------------------------------------------------------------------


def build_history_job(
    submission, schedd_job: dict | None, active_jobs: list[dict]
) -> dict:
    """Build a job dict from a local DB submission record and schedd data.

    Args:
        submission: A JobSubmission DB record.
        schedd_job: Optional schedd job dict (for real-time status).
        active_jobs: List of active jobs from the schedd.

    Returns:
        A job dict in the format expected by the frontend.
    """
    from app.condor import JOB_STATUS_MAP

    if schedd_job:
        # Use the real status from the schedd
        real_status = schedd_job.get("JobStatus", 4)
        cmd = schedd_job.get("Cmd", "")
        args = schedd_job.get("Args", "")

        # If the command is /bin/sh (shell job), try to extract the original
        # shell command from the submission record in the local database.
        if cmd == "/bin/sh":
            try:
                desc = submission.submit_description
                if desc and desc.strip().startswith("{"):
                    parsed = json.loads(desc)
                    shell_cmd = parsed.get("shell", "")
                    if shell_cmd:
                        cmd = shell_cmd
                        args = ""
            except json.JSONDecodeError, AttributeError:
                pass

        return {
            "ClusterId": submission.cluster_id,
            "ProcId": schedd_job.get("ProcId", 0),
            "JobStatus": real_status,
            "JobStatusName": JOB_STATUS_MAP.get(real_status, "Unknown"),
            "Owner": schedd_job.get("Owner", "—"),
            "Cmd": cmd,
            "Args": args,
            "RequestCpus": schedd_job.get("RequestCpus", "—"),
            "RequestMemory": schedd_job.get("RequestMemory", "—"),
            "RequestDisk": schedd_job.get("RequestDisk", "—"),
            "QDate": schedd_job.get("QDate", 0),
            "JobStartDate": schedd_job.get("JobStartDate"),
            "CompletionDate": schedd_job.get("CompletionDate"),
            "HoldReason": schedd_job.get("HoldReason", ""),
            "RemoteHost": schedd_job.get("RemoteHost", ""),
            "ImageSize": schedd_job.get("ImageSize", 0),
            "DiskUsage": schedd_job.get("DiskUsage", 0),
            "ExitCode": schedd_job.get("ExitCode", 0),
            "ExitBySignal": schedd_job.get("ExitBySignal", False),
            "JobCurrentStartDate": schedd_job.get("JobCurrentStartDate"),
            "NumJobStarts": schedd_job.get("NumJobStarts", 1),
            "NumShadowStarts": schedd_job.get("NumShadowStarts", 1),
            "JobBatchName": schedd_job.get("JobBatchName", submission.name),
            "RemoteWallClockTime": schedd_job.get("RemoteWallClockTime", 0),
            "CumulativeRemoteSysCpu": schedd_job.get("CumulativeRemoteSysCpu", 0),
            "CumulativeRemoteUserCpu": schedd_job.get("CumulativeRemoteUserCpu", 0),
        }
    else:
        # Job is no longer in the schedd — mark as Completed
        cmd = ""
        request_cpus = "—"
        request_memory = "—"
        request_disk = "—"
        try:
            if submission.submit_description.strip().startswith("{"):
                desc = json.loads(submission.submit_description)
                cmd = desc.get("executable", desc.get("shell", ""))
                if "request_cpus" in desc:
                    request_cpus = desc["request_cpus"]
                if "request_memory" in desc:
                    request_memory = desc["request_memory"]
                if "request_disk" in desc:
                    request_disk = desc["request_disk"]
        except json.JSONDecodeError, AttributeError:
            cmd = ""

        qdate = (
            int(submission.submitted_at.timestamp()) if submission.submitted_at else 0
        )

        return {
            "ClusterId": submission.cluster_id,
            "ProcId": 0,
            "JobStatus": 4,
            "JobStatusName": "Completed",
            "Owner": "—",
            "Cmd": cmd,
            "Args": "",
            "RequestCpus": request_cpus,
            "RequestMemory": request_memory,
            "RequestDisk": request_disk,
            "QDate": qdate,
            "JobStartDate": None,
            "CompletionDate": None,
            "HoldReason": "",
            "RemoteHost": "",
            "ImageSize": 0,
            "DiskUsage": 0,
            "ExitCode": 0,
            "ExitBySignal": False,
            "JobCurrentStartDate": None,
            "NumJobStarts": 1,
            "NumShadowStarts": 1,
            "JobBatchName": submission.name,
            "RemoteWallClockTime": 0,
            "CumulativeRemoteSysCpu": 0,
            "CumulativeRemoteUserCpu": 0,
        }
