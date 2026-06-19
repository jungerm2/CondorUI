"""REST API blueprint for HTCondor job management."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from app import db
from app.condor import (
    DEFAULT_CONSTRAINT,
    act_on_job,
    daemon_available,
    get_job_file_content,
    get_job_log,
    get_job_log_file_paths,
    qedit_job,
    query_history,
    query_jobs,
    submit_from_file,
    submit_job,
)
from app.models import ContainerImage, JobSubmission, SubmitTemplate, UploadedFile
from app.utils import (
    resolve_shell_commands,
    save_uploaded_stream,
)

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


# These functions are now imported from app.utils
# _save_uploaded_stream → save_uploaded_stream
# _resolve_shell_commands → resolve_shell_commands


def _resolve_path(path: str) -> str:
    """Resolve a path to an absolute, normalized string."""
    return str(Path(path).resolve())


def _remove_empty_parents(path: Path) -> None:
    """Remove empty ancestor directories, stopping at the first non-empty one."""
    for parent in [path, *path.parents]:
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            else:
                break
        except OSError, PermissionError:
            break


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@api_bp.errorhandler(Exception)
def handle_error(e: Exception):
    logger.exception("Unhandled API error")
    return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@api_bp.route("/health")
def health_check():
    """Lightweight health check — does not query the schedd."""
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Job queries
# ---------------------------------------------------------------------------


@api_bp.route("/jobs")
def list_jobs():
    """List active jobs, with optional filters and pagination."""
    if not daemon_available():
        return jsonify(
            {
                "jobs": [],
                "count": 0,
                "total": 0,
                "has_more": False,
                "limit": 0,
                "offset": 0,
                "daemon_unavailable": True,
                "message": "HTCondor daemon is not available.",
            }
        )

    constraint_parts: list[str] = []

    owner = request.args.get("owner")
    if owner:
        constraint_parts.append(f'Owner == "{owner}"')

    status = request.args.get("status")
    if status and status.isdigit():
        constraint_parts.append(f"JobStatus == {status}")

    cluster_id = request.args.get("cluster_id")
    if cluster_id and cluster_id.isdigit():
        constraint_parts.append(f"ClusterId == {cluster_id}")

    constraint = (
        " && ".join(constraint_parts) if constraint_parts else DEFAULT_CONSTRAINT
    )

    try:
        limit = request.args.get("limit", 200, type=int)
        offset = request.args.get("offset", 0, type=int)
        limit = min(limit, 5000)

        jobs = query_jobs(constraint=constraint)
        total = len(jobs)
        paginated = jobs[offset : offset + limit]
        has_more = (offset + limit) < total

        # Resolve shell commands (/bin/sh) to the original shell command
        # from the submission record in the local database.
        resolve_shell_commands(paginated)

        return jsonify(
            {
                "jobs": paginated,
                "count": len(paginated),
                "total": total,
                "has_more": has_more,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:cluster_id>")
def get_cluster(cluster_id):
    """Get all procs for a specific cluster."""
    if not daemon_available():
        return jsonify(
            {
                "cluster_id": cluster_id,
                "jobs": [],
                "count": 0,
                "daemon_unavailable": True,
                "message": "HTCondor daemon is not available.",
            }
        )
    try:
        cid = int(cluster_id)
        jobs = query_jobs(constraint=f"ClusterId == {cid}")
        if not jobs:
            jobs = query_history(constraint=f"ClusterId == {cid}", limit=200)
        return jsonify({"cluster_id": cluster_id, "jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# History — reads from our local database (avoids slow condor_history queries)
# ---------------------------------------------------------------------------


@api_bp.route("/history")
def list_history():
    """List all known submissions with real-time status from the schedd.

    Reads from the local JobSubmission table (fast), then cross-references
    with the schedd to show the actual status of each cluster.  Clusters
    still in the schedd (idle / running / held) show their real status;
    clusters no longer in the schedd are marked Completed.
    """
    limit = request.args.get(
        "limit", current_app.config["MAX_HISTORY_RESULTS"], type=int
    )
    try:
        submissions = (
            JobSubmission.query.order_by(JobSubmission.submitted_at.desc())
            .limit(limit)
            .all()
        )

        # Build a cluster_id → status lookup from the schedd (fast, cached)
        schedd_statuses: dict[int, dict] = {}
        if daemon_available():
            try:
                cluster_ids = sorted({s.cluster_id for s in submissions})
                if cluster_ids:
                    constraint = " || ".join(
                        f"ClusterId == {cid}" for cid in cluster_ids
                    )
                    active_jobs = query_jobs(
                        constraint=constraint,
                        projection=[
                            "ClusterId",
                            "ProcId",
                            "JobStatus",
                            "Owner",
                            "Cmd",
                            "Args",
                            "QDate",
                            "JobStartDate",
                            "CompletionDate",
                            "HoldReason",
                            "RemoteHost",
                            "RemoteWallClockTime",
                            "ExitCode",
                            "ExitBySignal",
                            "JobBatchName",
                            "RequestCpus",
                            "RequestMemory",
                            "RequestDisk",
                        ],
                    )
                    # Only keep the first proc per cluster (ProcId == 0 prefered)
                    for job in active_jobs:
                        cid = job.get("ClusterId")
                        if cid is not None:
                            # Keep proc 0 if available, otherwise overwrite
                            if cid not in schedd_statuses or job.get("ProcId") == 0:
                                schedd_statuses[cid] = job
            except Exception:
                logger.warning(
                    "Could not query schedd for history statuses", exc_info=True
                )

        from app.condor import JOB_STATUS_MAP

        # Transform local DB records into the job-like format expected by the frontend
        jobs = []
        for sub in submissions:
            schedd_job = schedd_statuses.get(sub.cluster_id)

            if schedd_job:
                # Use the real status from the schedd
                real_status = schedd_job.get("JobStatus", 4)
                cmd = schedd_job.get("Cmd", "")
                args = schedd_job.get("Args", "")

                # If the command is /bin/sh (shell job), try to extract the original
                # shell command from the submission record in the local database.
                if cmd == "/bin/sh":
                    try:
                        desc = sub.submit_description
                        if desc and desc.strip().startswith("{"):
                            parsed = json.loads(desc)
                            shell_cmd = parsed.get("shell", "")
                            if shell_cmd:
                                cmd = shell_cmd
                                args = ""
                    except json.JSONDecodeError, AttributeError:
                        pass

                jobs.append(
                    {
                        "ClusterId": sub.cluster_id,
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
                        "JobBatchName": schedd_job.get("JobBatchName", sub.name),
                        "RemoteWallClockTime": schedd_job.get("RemoteWallClockTime", 0),
                        "CumulativeRemoteSysCpu": schedd_job.get(
                            "CumulativeRemoteSysCpu", 0
                        ),
                        "CumulativeRemoteUserCpu": schedd_job.get(
                            "CumulativeRemoteUserCpu", 0
                        ),
                    }
                )
            else:
                # Job is no longer in the schedd — mark as Completed
                cmd = ""
                request_cpus = "—"
                request_memory = "—"
                request_disk = "—"
                try:
                    if sub.submit_description.strip().startswith("{"):
                        desc = json.loads(sub.submit_description)
                        cmd = desc.get("executable", desc.get("shell", ""))
                        # Extract resource requests from submit description
                        if "request_cpus" in desc:
                            request_cpus = desc["request_cpus"]
                        if "request_memory" in desc:
                            request_memory = desc["request_memory"]
                        if "request_disk" in desc:
                            request_disk = desc["request_disk"]
                except json.JSONDecodeError, AttributeError:
                    cmd = ""

                qdate = int(sub.submitted_at.timestamp()) if sub.submitted_at else 0

                jobs.append(
                    {
                        "ClusterId": sub.cluster_id,
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
                        "JobBatchName": sub.name,
                        "RemoteWallClockTime": 0,
                        "CumulativeRemoteSysCpu": 0,
                        "CumulativeRemoteUserCpu": 0,
                    }
                )

        return jsonify({"jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------


@api_bp.route("/submit", methods=["POST"])
def submit():
    """Submit a job from a JSON submit description."""
    data = request.get_json()
    if not data or "submit" not in data:
        return jsonify({"error": "Missing 'submit' in request body"}), 400

    submit_dict = data["submit"]
    count = data.get("count", 1)
    itemdata = data.get("itemdata")
    name = data.get("name", "Untitled Job")

    try:
        if itemdata:
            cluster_id, num_procs = submit_job(
                submit_dict,
                count=len(itemdata),
                itemdata=itemdata,
                name=name,
            )
        else:
            cluster_id, num_procs = submit_job(submit_dict, count=count, name=name)

        return jsonify(
            {
                "cluster_id": cluster_id,
                "num_procs": num_procs,
                "message": f"Submitted cluster {cluster_id} with {num_procs} proc(s)",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/submit/file", methods=["POST"])
def submit_file():
    """Submit from an uploaded .sub file."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    name = request.form.get("name", file.filename)

    try:
        content = file.read().decode("utf-8")

        cluster_id, num_procs = submit_from_file(content, name=name)

        return jsonify(
            {
                "cluster_id": cluster_id,
                "num_procs": num_procs,
                "message": f"Submitted cluster {cluster_id} with {num_procs} proc(s)",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# File management — upload, list, rename, delete, stage to OSDF
# ---------------------------------------------------------------------------


@api_bp.route("/files", methods=["GET"])
def list_files():
    """List all uploaded files."""
    files = UploadedFile.query.order_by(UploadedFile.uploaded_at.desc()).all()
    return jsonify({"files": [f.to_dict() for f in files], "count": len(files)})


@api_bp.route("/files", methods=["POST"])
def upload_files():
    """Upload a file and create a DB record.

    Expects the raw file as the request body with:
      - Content-Type: application/octet-stream
      - X-Upload-Filename: original filename (required)
    """
    original_filename = request.headers.get("X-Upload-Filename", "").strip()
    if not original_filename:
        return jsonify({"error": "Missing 'X-Upload-Filename' header"}), 400

    upload_dir = current_app.config["UPLOAD_DIR"]

    try:
        unique_name, size = save_uploaded_stream(
            request.stream, upload_dir, original_filename
        )

        uploaded_file = UploadedFile(
            filename=unique_name,
            original_name=original_filename,
            local_path=str(Path(upload_dir) / unique_name),
            osdf_path=None,
            size=size,
        )
        db.session.add(uploaded_file)
        db.session.commit()

        return jsonify(uploaded_file.to_dict()), 201
    except Exception as e:
        logger.exception("File upload failed")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/files/<int:file_id>", methods=["PUT"])
def rename_file(file_id: int):
    """Rename an uploaded file (display name only)."""
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing 'filename' in request body"}), 400

    uploaded_file = UploadedFile.query.get_or_404(file_id)
    uploaded_file.filename = data["filename"]
    db.session.commit()
    return jsonify(uploaded_file.to_dict())


@api_bp.route("/files/<int:file_id>", methods=["DELETE"])
def delete_file(file_id: int):
    """Delete an uploaded file from disk/OSDF and the database."""
    uploaded_file = UploadedFile.query.get_or_404(file_id)

    # Remove from local disk if present
    if uploaded_file.local_path and Path(uploaded_file.local_path).exists():
        p = Path(uploaded_file.local_path)
        p.unlink()
        _remove_empty_parents(p.parent)

    # Remove from OSDF staging if present
    if uploaded_file.osdf_path and Path(uploaded_file.osdf_path).exists():
        p = Path(uploaded_file.osdf_path)
        p.unlink()
        _remove_empty_parents(p.parent)

    db.session.delete(uploaded_file)
    db.session.commit()
    return jsonify({"message": f"File '{uploaded_file.filename}' deleted"})


@api_bp.route("/files/<int:file_id>/stage", methods=["POST"])
def stage_file(file_id: int):
    """Move a file to the OSDF uploads subdirectory with a unique name."""
    uploaded_file = UploadedFile.query.get_or_404(file_id)

    if uploaded_file.osdf_path:
        return jsonify({"error": "File is already staged to OSDF"}), 400

    if not uploaded_file.local_path or not Path(uploaded_file.local_path).exists():
        return jsonify({"error": "Local file not found on disk"}), 404

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    import uuid

    file_uuid = uuid.uuid4().hex
    rel_name = f"{file_uuid}/{uploaded_file.original_name}"
    osdf_dest = _resolve_path(str(Path(osdf_root) / "uploads" / rel_name))
    Path(osdf_dest).parent.mkdir(parents=True, exist_ok=True)

    # Move the file (not copy) — only one copy exists
    shutil.move(uploaded_file.local_path, osdf_dest)

    # Clean up empty parent directories from the source location
    src_parent = Path(uploaded_file.local_path).parent
    _remove_empty_parents(src_parent)

    uploaded_file.local_path = None
    uploaded_file.osdf_path = osdf_dest
    uploaded_file.filename = rel_name
    db.session.commit()

    return jsonify(uploaded_file.to_dict())


@api_bp.route("/files/<int:file_id>/unstage", methods=["POST"])
def unstage_file(file_id: int):
    """Move a staged (OSDF) file back to the local upload directory."""
    uploaded_file = UploadedFile.query.get_or_404(file_id)

    if not uploaded_file.osdf_path:
        return jsonify({"error": "File is not staged to OSDF"}), 400

    if not Path(uploaded_file.osdf_path).exists():
        return jsonify({"error": "OSDF file not found on disk"}), 404

    upload_dir = current_app.config["UPLOAD_DIR"]

    # Generate a unique name in the local upload directory
    import uuid

    file_uuid = uuid.uuid4().hex
    rel_name = f"{file_uuid}/{uploaded_file.original_name}"
    local_dest = str(Path(upload_dir) / rel_name)
    Path(local_dest).parent.mkdir(parents=True, exist_ok=True)

    # Move the file back
    shutil.move(uploaded_file.osdf_path, local_dest)

    # Clean up empty parent directories from the OSDF source location
    src_parent = Path(uploaded_file.osdf_path).parent
    _remove_empty_parents(src_parent)

    uploaded_file.osdf_path = None
    uploaded_file.local_path = local_dest
    uploaded_file.filename = rel_name
    db.session.commit()

    return jsonify(uploaded_file.to_dict())


# ---------------------------------------------------------------------------
# Quota information
# ---------------------------------------------------------------------------


@api_bp.route("/quotas")
def get_quotas():
    """Get disk quota information from the `get_quotas` command."""
    try:
        result = subprocess.run(
            ["get_quotas"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {"error": f"get_quotas failed: {result.stderr.strip()}"}
            ), 500

        # Parse the tabular output
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return jsonify({"quotas": []})

        headers_raw = lines[0].split()
        # Map header names to canonical keys
        header_map = {
            "Path": "path",
            "Disk_Used(GB)": "disk_used_gb",
            "Disk_Limit(GB)": "disk_limit_gb",
            "Files_Used": "files_used",
            "File_Limit": "file_limit",
        }
        headers = []
        for h in headers_raw:
            headers.append(header_map.get(h, h.lower().replace(" ", "_")))

        quotas = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < len(headers):
                continue
            entry = {}
            for i, h in enumerate(headers):
                val = parts[i]
                # Try numeric conversion
                try:
                    if "." in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError, TypeError:
                    pass
                entry[h] = val
            quotas.append(entry)

        return jsonify({"quotas": quotas})
    except FileNotFoundError:
        return jsonify({"error": "get_quotas command not found on this system"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "get_quotas timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Container management — list, pull, upload, rename, delete
# ---------------------------------------------------------------------------


@api_bp.route("/containers", methods=["GET"])
def list_containers():
    """List all container images."""
    containers = ContainerImage.query.order_by(ContainerImage.created_at.desc()).all()
    return jsonify(
        {"containers": [c.to_dict() for c in containers], "count": len(containers)}
    )


@api_bp.route("/containers/pull", methods=["POST"])
def pull_container():
    """Pull a Docker image and convert to Apptainer .sif.

    Request JSON:
    {
        "image": "docker://ubuntu:latest",
        "name": "Ubuntu Latest"
    }
    """
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' in request body"}), 400

    image_ref = data["image"].strip()

    # Validate the image reference has a proper scheme prefix
    if "://" not in image_ref:
        return jsonify(
            {"error": "Invalid image reference. Please include a scheme prefix."}
        ), 400

    name = data.get("name", "").strip() or Path(image_ref).name

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    containers_dir = Path(osdf_root) / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    # Generate a unique filename: uuid/safe_name.sif
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.lower())
    pull_uuid = uuid.uuid4().hex
    unique_name = f"{pull_uuid}/{safe_name}.sif"
    dest_path = containers_dir / unique_name
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Run apptainer pull
        logger.info("Pulling container: %s -> %s", image_ref, dest_path)
        result = subprocess.run(
            ["apptainer", "pull", str(dest_path), image_ref],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error("apptainer pull failed: %s", result.stderr)
            return jsonify(
                {"error": f"apptainer pull failed: {result.stderr[:500]}"}
            ), 500

        size = dest_path.stat().st_size

        container = ContainerImage(
            name=name,
            filename=unique_name,
            source=image_ref,
            size=size,
        )
        db.session.add(container)
        db.session.commit()

        return jsonify(container.to_dict()), 201

    except subprocess.TimeoutExpired:
        return jsonify({"error": "apptainer pull timed out after 600 seconds"}), 500
    except FileNotFoundError:
        return jsonify(
            {
                "error": "apptainer command not found. Is Apptainer/Singularity installed?"
            }
        ), 500
    except Exception as e:
        logger.exception("Container pull failed")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/containers/pull/stream")
def pull_container_stream():
    """Stream apptainer pull output via Server-Sent Events.

    Query parameters:
        image (required): Docker/OCI image reference (e.g., docker://ubuntu:latest)
        name (optional): Display name for the container
    """
    import pty
    import select

    from flask import stream_with_context
    from flask.wrappers import Response

    image_ref = request.args.get("image", "").strip()
    if not image_ref:

        def err_gen():
            yield "event: error\ndata: Missing 'image' query parameter\n\n"

        return Response(err_gen(), mimetype="text/event-stream")

    if "://" not in image_ref:

        def err_gen():
            yield "event: error\ndata: Invalid image reference. Please include a scheme prefix (e.g., docker://...)\n\n"

        return Response(err_gen(), mimetype="text/event-stream")

    name = request.args.get("name", "").strip() or Path(image_ref).name

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:

        def err_gen():
            yield "event: error\ndata: OSDF root path is not configured\n\n"

        return Response(err_gen(), mimetype="text/event-stream")

    containers_dir = Path(osdf_root) / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.lower())
    pull_uuid = uuid.uuid4().hex
    unique_name = f"{pull_uuid}/{safe_name}.sif"
    dest_path = containers_dir / unique_name
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Compile ANSI escape code regex once for performance
    # Matches: \x1b[<digits>;<digits>...<letter> (CSI sequences)
    #          \x1b[<digits>;<digits>... (SGR, cursor movement, etc.)
    #          \x1b[<letter> (single-char sequences like \x1b[K, \x1b[G)
    #          \x1b]<digits>;<digits>...\x1b\\ (OSC sequences)
    #          \x1b[<digits>;<digits>...<letter> (all CSI)
    ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][0-9;]*[a-zA-Z]|\x1b[^[]")

    def generate():
        command = [
            "apptainer",
            "build",
            "--ignore-proot",
            "--force",
            str(dest_path),
            image_ref,
        ]
        yield f"event: start\ndata: {json.dumps({'filename': unique_name, 'command': ' '.join(command)})}\n\n"

        logger.info("Pulling container: %s -> %s", image_ref, dest_path)

        try:
            # Pass environment variables to apptainer, including overrides
            # for common issues (kernel ptrace bugs, SUID-less installs).
            env = os.environ.copy()

            # Also pick up any APPTAINER_* vars from the process environment
            for key in (
                "APPTAINER_TMPDIR",
                "APPTAINER_CACHEDIR",
                "APPTAINER_PULLFOLDER",
                "APPTAINER_BIND",
                "APPTAINER_CONTAINALL",
                "SINGULARITY_TMPDIR",
                "SINGULARITY_CACHEDIR",
                "SINGULARITY_PULLFOLDER",
            ):
                val = os.environ.get(key)
                if val:
                    env[key] = val

            # Allocate a PTY so apptainer thinks it's writing to a terminal.
            # This is necessary because apptainer (via the containers/image
            # library) suppresses progress bars when stdout is not a TTY.
            # Using shell=True helps ensure the PTY is properly set up.
            master_fd, slave_fd = pty.openpty()

            # Build the command string for shell=True
            cmd_str = " ".join(shlex.quote(c) for c in command)

            process = subprocess.Popen(
                cmd_str,
                stdout=slave_fd,
                stderr=subprocess.STDOUT,
                shell=True,
                close_fds=True,
                env=env,
            )

            os.close(slave_fd)

            # Read from the PTY master fd in 4096-byte chunks, then split on
            # newlines to emit individual lines.  apptainer's progress bars
            # use \r to overwrite lines in-place, which will appear as
            # separate \n-delimited chunks after the split — the frontend's
            # appendOrReplaceLastLine() handles replacing the last line.
            while True:
                r, _w, _e = select.select([master_fd], [], [], 0.5)
                if not r:
                    ret = process.poll()
                    if ret is not None:
                        break
                    continue

                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break

                # Decode and split on \n (which also catches \r\n pairs)
                text = data.decode("utf-8", errors="replace")
                for raw_line in text.split("\n"):
                    if not raw_line:
                        continue
                    # Strip ANSI escape codes
                    clean = ANSI_ESCAPE.sub("", raw_line)
                    if clean:
                        yield f"data: {clean}\n\n"

            os.close(master_fd)
            return_code = process.wait()

            if return_code != 0:
                logger.error("apptainer pull failed with code %d", return_code)
                yield f"event: error\ndata: apptainer pull failed with exit code {return_code}\n\n"
                return

            size = dest_path.stat().st_size

            container = ContainerImage(
                name=name,
                filename=unique_name,
                source=image_ref,
                size=size,
            )
            db.session.add(container)
            db.session.commit()

            yield f"event: complete\ndata: {json.dumps(container.to_dict())}\n\n"

        except FileNotFoundError:
            yield "event: error\ndata: apptainer command not found. Is Apptainer/Singularity installed?\n\n"
        except Exception as e:
            logger.exception("Container pull failed")
            yield f"event: error\ndata: {str(e)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api_bp.route("/containers/upload", methods=["POST"])
def upload_container():
    """Upload an existing .sif file to the containers directory.

    Expects the raw .sif file as the request body with:
      - Content-Type: application/octet-stream
      - X-Container-Filename: original filename (for .sif validation)
      - X-Container-Name: optional display name
    """
    original_filename = request.headers.get("X-Container-Filename", "").strip()
    if not original_filename:
        return jsonify({"error": "Missing 'X-Container-Filename' header"}), 400

    if not original_filename.lower().endswith(".sif"):
        return jsonify({"error": "Only .sif files are accepted"}), 400

    name = (
        request.headers.get("X-Container-Name", "").strip()
        or Path(original_filename).stem
    )

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    containers_dir = str(Path(osdf_root) / "containers")

    try:
        unique_name, size = save_uploaded_stream(
            request.stream, containers_dir, original_filename, name=name
        )

        container = ContainerImage(
            name=name,
            filename=unique_name,
            source=f"uploaded:{original_filename}",
            size=size,
        )
        db.session.add(container)
        db.session.commit()

        return jsonify(container.to_dict()), 201
    except Exception as e:
        logger.exception("Container upload failed")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/containers/<int:container_id>", methods=["PUT"])
def rename_container(container_id: int):
    """Rename a container (display name only)."""
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing 'name' in request body"}), 400

    container = ContainerImage.query.get_or_404(container_id)
    container.name = data["name"]
    db.session.commit()
    return jsonify(container.to_dict())


@api_bp.route("/containers/<int:container_id>", methods=["DELETE"])
def delete_container(container_id: int):
    """Delete a container image from disk and the database."""
    container = ContainerImage.query.get_or_404(container_id)

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if osdf_root:
        file_path = Path(osdf_root) / "containers" / container.filename
        if file_path.exists():
            file_path.unlink()
            _remove_empty_parents(file_path.parent)

    db.session.delete(container)
    db.session.commit()
    return jsonify({"message": f"Container '{container.name}' deleted"})


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


@api_bp.route("/jobs/<job_id>/hold", methods=["POST"])
def hold_job(job_id):
    """Hold a job."""
    try:
        result = act_on_job("hold", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<job_id>/release", methods=["POST"])
def release_job(job_id):
    """Release a held job."""
    try:
        result = act_on_job("release", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<job_id>", methods=["DELETE"])
def remove_job(job_id):
    """Remove a job."""
    try:
        result = act_on_job("remove", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Job logs & file content
# ---------------------------------------------------------------------------


@api_bp.route("/jobs/<int:cluster_id>/log")
def job_log(cluster_id: int):
    """Get the job log content."""
    proc_id = request.args.get("proc", 0, type=int)
    tail = request.args.get("tail", 200, type=int)
    try:
        log_content = get_job_log(cluster_id, proc_id=proc_id, tail=tail)
        return jsonify(
            {"cluster_id": cluster_id, "proc_id": proc_id, "log": log_content}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:cluster_id>/<int:proc_id>/files")
def job_files(cluster_id: int, proc_id: int):
    """Get log, stdout, and stderr file contents for a specific job proc."""
    tail = request.args.get("tail", 500, type=int)
    is_download = request.args.get("download", "0") == "1"

    try:
        paths = get_job_log_file_paths(cluster_id, proc_id=proc_id)

        if is_download:
            file_type = request.args.get("file", "log")
            file_path = paths.get(file_type)
            if not file_path or not Path(file_path).exists():
                return jsonify({"error": f"File not found: {file_type}"}), 404

            filename_map = {
                "log": f"job_{cluster_id}.log",
                "out": f"job_{cluster_id}_{proc_id}.out",
                "err": f"job_{cluster_id}_{proc_id}.err",
            }
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename_map.get(
                    file_type, f"job_{cluster_id}_{proc_id}.txt"
                ),
            )

        log_content = get_job_file_content(paths.get("log", ""), tail=tail)
        stdout_content = get_job_file_content(paths.get("out", ""), tail=tail)
        stderr_content = get_job_file_content(paths.get("err", ""), tail=tail)

        return jsonify(
            {
                "cluster_id": cluster_id,
                "proc_id": proc_id,
                "paths": paths,
                "log": log_content or "No log content yet or file not found.",
                "stdout": stdout_content or "No stdout content yet or file not found.",
                "stderr": stderr_content or "No stderr content yet or file not found.",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:cluster_id>/details")
def job_details(cluster_id: int):
    """Get complete job details."""
    proc_id = request.args.get("proc", 0, type=int)
    tail = request.args.get("tail", 500, type=int)
    try:
        jobs = query_jobs(
            constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}"
        )
        if not jobs:
            jobs = query_history(
                constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
                limit=1,
            )
        job = jobs[0] if jobs else {}

        # If the command is /bin/sh (shell job), try to extract the original
        # shell command from the submission record in the local database.
        submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        submission_name = submission.name if submission else "Job Subbed Outside Web UI"

        if job and submission and job.get("Cmd") == "/bin/sh":
            try:
                desc = submission.submit_description
                if desc and desc.strip().startswith("{"):
                    parsed = json.loads(desc)
                    shell_cmd = parsed.get("shell", "")
                    if shell_cmd:
                        # Override Cmd with the original shell command for display
                        job["Cmd"] = shell_cmd
                        # Clear Args since the shell command is now the full Cmd
                        job["Args"] = ""
            except json.JSONDecodeError, AttributeError:
                pass

        paths = get_job_log_file_paths(cluster_id, proc_id=proc_id)

        log_content = get_job_file_content(paths.get("log", ""), tail=tail)
        stdout_content = get_job_file_content(paths.get("out", ""), tail=tail)
        stderr_content = get_job_file_content(paths.get("err", ""), tail=tail)

        return jsonify(
            {
                "cluster_id": cluster_id,
                "proc_id": proc_id,
                "job": job,
                "submission_name": submission_name,
                "paths": paths,
                "log": log_content or "No log content yet or file not found.",
                "stdout": stdout_content or "No stdout content yet or file not found.",
                "stderr": stderr_content or "No stderr content yet or file not found.",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Submit templates
# ---------------------------------------------------------------------------


@api_bp.route("/templates")
def list_templates():
    """List all saved submit templates."""
    templates = SubmitTemplate.query.order_by(SubmitTemplate.updated_at.desc()).all()
    return jsonify({"templates": [t.to_dict() for t in templates]})


@api_bp.route("/templates", methods=["POST"])
def create_template():
    """Save a new submit template."""
    data = request.get_json()
    if not data or "name" not in data or "submit_data" not in data:
        return jsonify({"error": "Missing 'name' or 'submit_data'"}), 400

    template = SubmitTemplate(
        name=data["name"],
        description=data.get("description", ""),
        submit_data=json.dumps(data["submit_data"])
        if isinstance(data["submit_data"], dict)
        else data["submit_data"],
    )
    db.session.add(template)
    db.session.commit()

    return jsonify(template.to_dict()), 201


@api_bp.route("/templates/<int:template_id>", methods=["PUT"])
def update_template(template_id: int):
    """Update an existing template."""
    template = SubmitTemplate.query.get_or_404(template_id)
    data = request.get_json()

    if "name" in data:
        template.name = data["name"]
    if "description" in data:
        template.description = data["description"]
    if "submit_data" in data:
        template.submit_data = (
            json.dumps(data["submit_data"])
            if isinstance(data["submit_data"], dict)
            else data["submit_data"]
        )

    db.session.commit()
    return jsonify(template.to_dict())


@api_bp.route("/templates/<int:template_id>", methods=["DELETE"])
def delete_template(template_id: int):
    """Delete a template."""
    template = SubmitTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    return jsonify({"message": f"Template '{template.name}' deleted"})


# ---------------------------------------------------------------------------
# Submission history (from our database)
# ---------------------------------------------------------------------------


@api_bp.route("/qedit", methods=["POST"])
def qedit_job_route():
    """Edit a ClassAd attribute on a job (condor_qedit).

    Request JSON:
    {
        "cluster_id": 123,
        "proc_id": 0,
        "attr": "request_disk",
        "value": "4096"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    cluster_id = data.get("cluster_id")
    proc_id = data.get("proc_id", 0)
    attr = data.get("attr")
    value = data.get("value")

    if not cluster_id or not attr or not value:
        return jsonify(
            {"error": "Missing required fields: cluster_id, attr, value"}
        ), 400

    try:
        result = qedit_job(cluster_id, proc_id, attr, value)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/history/delete", methods=["POST"])
def delete_history():
    """Delete history entries from the local DB, logs, and optionally from the schedd.

    Request JSON:
    {
        "cluster_ids": [123, 456, ...]
    }
    """
    data = request.get_json()
    if not data or "cluster_ids" not in data:
        return jsonify({"error": "Missing 'cluster_ids' in request body"}), 400

    cluster_ids = data["cluster_ids"]
    if not isinstance(cluster_ids, list) or not cluster_ids:
        return jsonify({"error": "'cluster_ids' must be a non-empty list"}), 400

    results = []
    for cid in cluster_ids:
        try:
            # 1. Remove from schedd if still active
            if daemon_available():
                try:
                    act_on_job("remove", str(cid))
                except Exception:
                    pass  # Job may already be gone from schedd

            # 2. Delete from local DB
            submission = JobSubmission.query.filter_by(cluster_id=cid).first()
            if submission:
                # 3. Remove log directory from disk
                if submission.log_dir and Path(submission.log_dir).exists():
                    shutil.rmtree(submission.log_dir, ignore_errors=True)
                db.session.delete(submission)

            results.append({"cluster_id": cid, "success": True})
        except Exception as e:
            logger.error("Failed to delete cluster %d: %s", cid, e)
            results.append({"cluster_id": cid, "success": False, "error": str(e)})

    db.session.commit()
    return jsonify({"results": results, "count": len(results)})


@api_bp.route("/history/release", methods=["POST"])
def release_history():
    """Bulk-release held jobs.

    Request JSON:
    {
        "cluster_ids": [123, 456, ...]
    }
    """
    data = request.get_json()
    if not data or "cluster_ids" not in data:
        return jsonify({"error": "Missing 'cluster_ids' in request body"}), 400

    cluster_ids = data["cluster_ids"]
    if not isinstance(cluster_ids, list) or not cluster_ids:
        return jsonify({"error": "'cluster_ids' must be a non-empty list"}), 400

    results = []
    for cid in cluster_ids:
        try:
            result = act_on_job("release", str(cid))
            results.append({"cluster_id": cid, "success": True, "result": str(result)})
        except Exception as e:
            logger.error("Failed to release cluster %d: %s", cid, e)
            results.append({"cluster_id": cid, "success": False, "error": str(e)})

    return jsonify({"results": results, "count": len(results)})


@api_bp.route("/submissions")
def list_submissions():
    """List submissions made through this UI (from the local database)."""
    limit = request.args.get("limit", 100, type=int)
    submissions = (
        JobSubmission.query.order_by(JobSubmission.submitted_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"submissions": [s.to_dict() for s in submissions]})


# ---------------------------------------------------------------------------
# Output files — list and download output files transferred back from jobs
# ---------------------------------------------------------------------------


@api_bp.route("/output-files")
def list_output_files():
    """List all output files from completed jobs.

    Scans the OUTPUT_DIR directory for files and cross-references
    with JobSubmission records to show which job produced each file.
    """
    output_dir = current_app.config["OUTPUT_DIR"]
    output_path = Path(output_dir)

    if not output_path.exists():
        return jsonify({"output_files": [], "count": 0})

    # Get all job submissions that have output_dir set
    submissions = JobSubmission.query.filter(JobSubmission.output_dir.isnot(None)).all()

    output_files = []
    try:
        # Scan each job's output directory
        for sub in submissions:
            if not sub.output_dir:
                continue
            job_output_path = Path(sub.output_dir)
            if not job_output_path.exists():
                continue

            for f in job_output_path.iterdir():
                if f.is_file():
                    stat = f.stat()
                    output_files.append(
                        {
                            "filename": f.name,
                            "path": str(f),
                            "size": stat.st_size,
                            "modified_at": stat.st_mtime,
                            "cluster_id": sub.cluster_id,
                            "job_name": sub.name,
                        }
                    )

        # Sort by modified_at descending
        output_files.sort(key=lambda x: x.get("modified_at", 0), reverse=True)

        return jsonify({"output_files": output_files, "count": len(output_files)})
    except Exception as e:
        logger.exception("Failed to list output files")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/output-files/download/<int:cluster_id>/<path:filename>")
def download_output_file(cluster_id: int, filename: str):
    """Download a specific output file for a given job.

    Looks up the job's output directory from the JobSubmission record
    and resolves the file path from there.
    """
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission or not submission.output_dir:
        return jsonify({"error": f"Output directory not found for cluster {cluster_id}"}), 404

    file_path = Path(submission.output_dir) / filename

    if not file_path.exists():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=file_path.name,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/output-files/delete/<int:cluster_id>/<path:filename>", methods=["DELETE"])
def delete_output_file(cluster_id: int, filename: str):
    """Delete an output file for a given job."""
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission or not submission.output_dir:
        return jsonify({"error": f"Output directory not found for cluster {cluster_id}"}), 404

    file_path = Path(submission.output_dir) / filename

    if not file_path.exists():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        file_path.unlink()
        return jsonify({"message": f"Deleted output file: {filename}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
