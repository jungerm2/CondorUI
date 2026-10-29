"""Shared utility functions for the Condor Web UI."""

from __future__ import annotations

import json
import logging
import os
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
        except json.JSONDecodeError, AttributeError:
            pass


# ---------------------------------------------------------------------------
# Filesystem scanning — shared between uploads and containers
# ---------------------------------------------------------------------------
# Both uploads and containers are stored in UUID-named subdirectories
# (e.g., <base_dir>/<uuid>/<filename>).  The same scanning logic applies
# to both, parameterized by the base directory and an optional filter.


def safe_filename(name: str) -> str:
    """Sanitize a user-supplied filename to a single path component.

    Strips any directory components (e.g., ``../../etc/passwd`` →
    ``passwd``) and rejects empty/dot-only names.  Raises ``ValueError``
    for names that have no usable component.
    """
    cleaned = Path(str(name)).name
    if cleaned in ("", ".", ".."):
        raise ValueError(f"Invalid filename: {name!r}")
    return cleaned


def safe_path_component(name: str) -> str:
    """Legacy alias of :func:`safe_filename`."""
    return safe_filename(name)


def safe_join(base_dir: str, *relative: str) -> Path:
    """Join *relative* path components under *base_dir*, safely.

    Resolves the final path and verifies it stays inside *base_dir*.
    Raises ``ValueError`` if the path escapes the base directory (e.g.,
    via ``..`` components or symlinks pointing outside).

    Returns the resolved absolute ``Path``.
    """
    base = Path(base_dir).resolve()
    target = base.joinpath(*relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path escapes base directory: {'/'.join(relative)!r}")
    return target


def scan_uuid_directories(
    base_dir: str,
    *,
    file_filter: str | None = None,
    extra_fields: dict | None = None,
    recursive: bool = False,
) -> list[dict]:
    """Scan UUID-named subdirectories for uploaded files.

    ``recursive`` walks nested folders inside each UUID directory, preserving
    relative paths in ``filename``.
    """
    base_path = Path(base_dir)
    if not base_path.is_dir():
        return []

    def entry_for(path: Path, rel_name: str) -> dict | None:
        if file_filter and not path.name.endswith(file_filter):
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        entry = {
            "filename": rel_name,
            "original_name": path.name,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
        }
        if extra_fields:
            entry.update(extra_fields)
        return entry

    files: list[dict] = []
    try:
        subdirs = sorted(
            base_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return []

    for subdir in subdirs:
        if not subdir.is_dir() or subdir.is_symlink():
            continue
        if recursive:
            for dirpath, dirnames, filenames in os.walk(subdir):
                dirnames[:] = [
                    name for name in dirnames if not (Path(dirpath) / name).is_symlink()
                ]
                for name in filenames:
                    path = Path(dirpath) / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    rel = path.relative_to(subdir).as_posix()
                    entry = entry_for(path, f"{subdir.name}/{rel}")
                    if entry:
                        files.append(entry)
        else:
            try:
                children = subdir.iterdir()
            except OSError:
                continue
            for path in children:
                if not path.is_file() or path.is_symlink():
                    continue
                entry = entry_for(path, f"{subdir.name}/{path.name}")
                if entry:
                    files.append(entry)
    return files


# ---------------------------------------------------------------------------
# File upload helpers
# ---------------------------------------------------------------------------


def save_uploaded_stream(
    stream,
    dest_dir: str,
    original_filename: str,
    name: str | None = None,
    *,
    root_name: str | None = None,
    relative_path: str | None = None,
) -> tuple[str, int]:
    """Stream a raw uploaded file to disk.

    Folder uploads pass one shared ``root_name`` and a ``relative_path`` so
    files keep their directory tree; single uploads keep the UUID layout.
    """
    dest_path_obj = Path(dest_dir)
    dest_path_obj.mkdir(parents=True, exist_ok=True)

    if root_name is not None:
        if not relative_path:
            raise ValueError("Missing relative path")
        parts = [
            safe_path_component(part)
            for part in relative_path.replace("\\", "/").split("/")
            if part not in ("", ".")
        ]
        if not parts:
            raise ValueError("Invalid relative path")
        root = safe_path_component(root_name)
        dest_path = safe_join(str(dest_path_obj), root, *parts)
        rel_name = f"{root}/{Path(*parts).as_posix()}"
    else:
        # Strip any path components so a hostile client header cannot escape dest_dir
        original_filename = safe_path_component(original_filename)
        subdir = dest_path_obj / uuid.uuid4().hex
        dest_path = subdir / original_filename
        rel_name = f"{subdir.name}/{original_filename}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest_path.with_name(f".{dest_path.name}.{uuid.uuid4().hex}.part")
    try:
        with open(temporary, "wb") as f:
            shutil.copyfileobj(stream, f, length=1024 * 1024)
        temporary.replace(dest_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return rel_name, dest_path.stat().st_size


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
