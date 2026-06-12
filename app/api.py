"""REST API blueprint for HTCondor job management."""

from __future__ import annotations

import json
import logging
import os
import shutil

from flask import Blueprint, current_app, jsonify, request, send_file

from app import db
from app.condor import (
    DEFAULT_CONSTRAINT,
    act_on_job,
    daemon_available,
    get_job_file_content,
    get_job_log,
    get_job_log_file_paths,
    get_job_status_counts,
    qedit_job,
    query_history,
    query_jobs,
    submit_from_file,
    submit_job,
)
from app.models import JobSubmission, SubmitTemplate

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


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
        return jsonify({
            "jobs": [],
            "count": 0,
            "total": 0,
            "has_more": False,
            "limit": 0,
            "offset": 0,
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available."
        })

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

    constraint = " && ".join(constraint_parts) if constraint_parts else DEFAULT_CONSTRAINT

    try:
        limit = request.args.get("limit", 200, type=int)
        offset = request.args.get("offset", 0, type=int)
        limit = min(limit, 5000)

        jobs = query_jobs(constraint=constraint)
        total = len(jobs)
        paginated = jobs[offset:offset + limit]
        has_more = (offset + limit) < total

        return jsonify({
            "jobs": paginated,
            "count": len(paginated),
            "total": total,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<cluster_id>")
def get_cluster(cluster_id):
    """Get all procs for a specific cluster."""
    if not daemon_available():
        return jsonify({
            "cluster_id": cluster_id,
            "jobs": [],
            "count": 0,
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available."
        })
    try:
        cid = cluster_id.split(".")[0] if "." in str(cluster_id) else cluster_id
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
    limit = request.args.get("limit", current_app.config["MAX_HISTORY_RESULTS"], type=int)
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
                            "ClusterId", "ProcId", "JobStatus", "Owner",
                            "Cmd", "Args", "QDate", "JobStartDate",
                            "CompletionDate", "HoldReason", "RemoteHost",
                            "RemoteWallClockTime", "ExitCode", "ExitBySignal",
                            "JobBatchName",
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
                logger.warning("Could not query schedd for history statuses", exc_info=True)

        from app.condor import JOB_STATUS_MAP

        # Transform local DB records into the job-like format expected by the frontend
        jobs = []
        for sub in submissions:
            schedd_job = schedd_statuses.get(sub.cluster_id)

            if schedd_job:
                # Use the real status from the schedd
                real_status = schedd_job.get("JobStatus", 4)
                jobs.append({
                    "ClusterId": sub.cluster_id,
                    "ProcId": schedd_job.get("ProcId", 0),
                    "JobStatus": real_status,
                    "JobStatusName": JOB_STATUS_MAP.get(real_status, "Unknown"),
                    "Owner": schedd_job.get("Owner", "—"),
                    "Cmd": schedd_job.get("Cmd", ""),
                    "Args": schedd_job.get("Args", ""),
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
                    "CumulativeRemoteSysCpu": schedd_job.get("CumulativeRemoteSysCpu", 0),
                    "CumulativeRemoteUserCpu": schedd_job.get("CumulativeRemoteUserCpu", 0),
                })
            else:
                # Job is no longer in the schedd — mark as Completed
                cmd = ""
                try:
                    if sub.submit_description.strip().startswith("{"):
                        desc = json.loads(sub.submit_description)
                        cmd = desc.get("executable", desc.get("shell", ""))
                except (json.JSONDecodeError, AttributeError):
                    cmd = ""

                qdate = int(sub.submitted_at.timestamp()) if sub.submitted_at else 0

                jobs.append({
                    "ClusterId": sub.cluster_id,
                    "ProcId": 0,
                    "JobStatus": 4,
                    "JobStatusName": "Completed",
                    "Owner": "—",
                    "Cmd": cmd,
                    "Args": "",
                    "RequestCpus": "—",
                    "RequestMemory": "—",
                    "RequestDisk": "—",
                    "QDate": qdate,
                    "JobStartDate": None,
                    "CompletionDate": qdate,
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
                })

        return jsonify({"jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/stats")
def get_stats():
    """Get aggregate job status counts."""
    if not daemon_available():
        return jsonify({
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available."
        })
    try:
        counts = get_job_status_counts()
        return jsonify(counts)
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
        import uuid
        job_uuid = f"job_{uuid.uuid4().hex}"
        log_dir = os.path.join(current_app.config["JOB_LOGS_DIR"], job_uuid)
        os.makedirs(log_dir, exist_ok=True)

        if itemdata:
            cluster_id = submit_job(submit_dict, count=len(itemdata), itemdata=itemdata, log_dir=log_dir)
            num_procs = len(itemdata)
        else:
            cluster_id = submit_job(submit_dict, count=count, log_dir=log_dir)
            num_procs = count

        submission = JobSubmission(
            cluster_id=cluster_id,
            name=name,
            submit_description=json.dumps(submit_dict),
            num_procs=num_procs,
            log_dir=log_dir,
        )
        db.session.add(submission)
        db.session.commit()

        return jsonify({
            "cluster_id": cluster_id,
            "num_procs": num_procs,
            "message": f"Submitted cluster {cluster_id} with {num_procs} proc(s)",
        }), 201
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

        import uuid
        job_uuid = f"job_{uuid.uuid4().hex}"
        log_dir = os.path.join(current_app.config["JOB_LOGS_DIR"], job_uuid)
        os.makedirs(log_dir, exist_ok=True)

        cluster_id, num_procs = submit_from_file(content, log_dir=log_dir)

        submission = JobSubmission(
            cluster_id=cluster_id,
            name=name,
            submit_description=content,
            num_procs=num_procs,
            log_dir=log_dir,
        )
        db.session.add(submission)
        db.session.commit()

        return jsonify({
            "cluster_id": cluster_id,
            "num_procs": num_procs,
            "message": f"Submitted cluster {cluster_id} with {num_procs} proc(s)",
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# File upload (for OSDF staging)
# ---------------------------------------------------------------------------


@api_bp.route("/upload", methods=["POST"])
def upload_files():
    """Upload files, optionally staging them to the OSDF cache directory."""
    if "files" not in request.files:
        return jsonify({"error": "No files in request"}), 400

    files = request.files.getlist("files")
    upload_dir = current_app.config["UPLOAD_DIR"]
    osdf_path = current_app.config.get("OSDF_STAGING_PATH", "")

    saved: list[dict[str, str]] = []

    for f in files:
        if not f.filename:
            continue

        local_path = os.path.join(upload_dir, f.filename)
        f.save(local_path)
        entry: dict[str, str] = {"filename": f.filename, "local_path": local_path}

        if osdf_path:
            osdf_dest = os.path.join(osdf_path, f.filename)
            os.makedirs(os.path.dirname(osdf_dest), exist_ok=True)
            shutil.copy2(local_path, osdf_dest)
            entry["osdf_uri"] = f"osdf:///{f.filename}"
            entry["osdf_path"] = osdf_dest
        else:
            entry["osdf_uri"] = ""

        saved.append(entry)

    return jsonify({"uploaded": saved, "count": len(saved)}), 201


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
        return jsonify({"cluster_id": cluster_id, "proc_id": proc_id, "log": log_content})
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
            if not file_path or not os.path.exists(file_path):
                return jsonify({"error": f"File not found: {file_type}"}), 404

            filename_map = {"log": f"job_{cluster_id}.log", "out": f"job_{cluster_id}_{proc_id}.out", "err": f"job_{cluster_id}_{proc_id}.err"}
            return send_file(file_path, as_attachment=True, download_name=filename_map.get(file_type, f"job_{cluster_id}_{proc_id}.txt"))

        log_content = get_job_file_content(paths.get("log", ""), tail=tail)
        stdout_content = get_job_file_content(paths.get("out", ""), tail=tail)
        stderr_content = get_job_file_content(paths.get("err", ""), tail=tail)

        return jsonify({
            "cluster_id": cluster_id,
            "proc_id": proc_id,
            "paths": paths,
            "log": log_content or "No log content yet or file not found.",
            "stdout": stdout_content or "No stdout content yet or file not found.",
            "stderr": stderr_content or "No stderr content yet or file not found.",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:cluster_id>/details")
def job_details(cluster_id: int):
    """Get complete job details."""
    proc_id = request.args.get("proc", 0, type=int)
    tail = request.args.get("tail", 500, type=int)
    try:
        jobs = query_jobs(constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}")
        if not jobs:
            jobs = query_history(
                constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
                limit=1,
            )
        job = jobs[0] if jobs else {}

        paths = get_job_log_file_paths(cluster_id, proc_id=proc_id)

        log_content = get_job_file_content(paths.get("log", ""), tail=tail)
        stdout_content = get_job_file_content(paths.get("out", ""), tail=tail)
        stderr_content = get_job_file_content(paths.get("err", ""), tail=tail)

        submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        submission_name = submission.name if submission else "Job Subbed Outside Web UI"

        return jsonify({
            "cluster_id": cluster_id,
            "proc_id": proc_id,
            "job": job,
            "submission_name": submission_name,
            "paths": paths,
            "log": log_content or "No log content yet or file not found.",
            "stdout": stdout_content or "No stdout content yet or file not found.",
            "stderr": stderr_content or "No stderr content yet or file not found."
        })
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
        return jsonify({"error": "Missing required fields: cluster_id, attr, value"}), 400

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
                if submission.log_dir and os.path.exists(submission.log_dir):
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
