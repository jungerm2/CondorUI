"""Shared utility functions for the Condor Web UI."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shell command resolution
# ---------------------------------------------------------------------------


def resolve_commands(jobs: list[dict]) -> None:
    """Resolve Cmd attributes and JobBatchName to their original values from the DB.

    Handles two cases for Cmd:
    1. Shell jobs (Cmd == "/bin/sh"): Replace Cmd with the original shell
       command (e.g., "ls -al") stored in the submit_description.
    2. Executable jobs (Cmd is an absolute path): Replace Cmd with the
       original relative executable path from the submit description.

    Also resolves JobBatchName from the DB submission name when the ClassAd
    value is empty/null, since the web UI stores the submission name in the
    DB but does not set +JobBatchName in the submit description.

    Modifies the list in-place.
    """
    from app.models import JobSubmission

    # Collect all cluster IDs that need resolution
    cluster_ids = [
        j.get("ClusterId")
        for j in jobs
        if j.get("Cmd") == "/bin/sh"
        or Path(j.get("Cmd", "")).is_absolute()
        or not j.get("JobBatchName")
    ]
    if not cluster_ids:
        return

    submissions = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(cluster_ids)
    ).all()
    sub_map = {s.cluster_id: s for s in submissions}

    for job in jobs:
        sub = sub_map.get(job.get("ClusterId"))
        if not sub:
            continue

        # Resolve JobBatchName from DB submission name
        if not job.get("JobBatchName") and sub.name:
            job["JobBatchName"] = sub.name

        # Resolve Cmd from submit_description
        try:
            desc = sub.submit_description
            if not desc or not desc.strip().startswith("{"):
                continue
            parsed = json.loads(desc)

            cmd = job.get("Cmd", "")
            if cmd == "/bin/sh":
                shell_cmd = parsed.get("shell", "")
                if shell_cmd:
                    job["Cmd"] = shell_cmd
                    job["Args"] = ""
            elif Path(cmd).is_absolute():
                orig_exec = parsed.get("executable", "")
                if orig_exec and not Path(orig_exec).is_absolute():
                    job["Cmd"] = orig_exec
        except (json.JSONDecodeError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# Filesystem scanning — shared between uploads and containers
# ---------------------------------------------------------------------------
# Both uploads and containers are stored in UUID-named subdirectories
# (e.g., <base_dir>/<uuid>/<filename>).  The same scanning logic applies
# to both, parameterized by the base directory and an optional filter.


def scan_uuid_directories(
    base_dir: str,
    *,
    file_filter: str | None = None,
    extra_fields: dict | None = None,
) -> list[dict]:
    """Scan a directory of UUID-named subdirectories for files.

    Each subdirectory under *base_dir* is expected to be a UUID directory
    containing a single file.  Returns a list of file dicts sorted by
    modification time (newest first).

    Args:
        base_dir: The base directory to scan (e.g., UPLOAD_DIR).
        file_filter: Optional glob/suffix filter (e.g., ``.sif``).
                     If None, all files are included.
        extra_fields: Optional dict of extra fields to include in each
                      file dict (e.g., ``{"osdf_path": None}``).

    Returns:
        List of file dicts with keys: filename, original_name, size,
        modified_at, and any extra_fields provided.
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return []

    files = []
    for subdir in sorted(
        base_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        if not subdir.is_dir():
            continue
        for f in subdir.iterdir():
            if not f.is_file():
                continue
            if file_filter and not f.name.endswith(file_filter):
                continue
            stat = f.stat()
            rel_name = f"{subdir.name}/{f.name}"
            entry = {
                "filename": rel_name,
                "original_name": f.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }
            if extra_fields:
                entry.update(extra_fields)
            files.append(entry)
    return files


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
            "LastRemoteWallClockTime": schedd_job.get("LastRemoteWallClockTime", 0),
            "CumulativeSuspensionTime": schedd_job.get("CumulativeSuspensionTime", 0),
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
        except (json.JSONDecodeError, AttributeError):
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
