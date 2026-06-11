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
    """List active jobs, with optional filters and pagination.

    Query parameters:
        owner     — Filter by owner username
        status    — Filter by JobStatus code (1=Idle, 2=Running, 5=Held, etc.)
        cluster_id — Filter by cluster ID
        limit     — Max results to return (default 200, max 5000)
        offset    — Number of results to skip (default 0)
    """
    if not daemon_available():
        return jsonify({
            "jobs": [],
            "count": 0,
            "total": 0,
            "has_more": False,
            "limit": 0,
            "offset": 0,
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available. This is expected on a development machine without a running condor_schedd."
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
    """Get all procs for a specific cluster. Accepts bare cluster IDs or cluster.proc format."""
    if not daemon_available():
        return jsonify({
            "cluster_id": cluster_id,
            "jobs": [],
            "count": 0,
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available."
        })
    try:
        # Split cluster.proc if given, but query by cluster ID
        cid = cluster_id.split(".")[0] if "." in str(cluster_id) else cluster_id
        jobs = query_jobs(constraint=f"ClusterId == {cid}")
        if not jobs:
            jobs = query_history(constraint=f"ClusterId == {cid}", limit=200)
        return jsonify({"cluster_id": cluster_id, "jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/history")
def list_history():
    """List completed jobs from condor_history."""
    if not daemon_available():
        return jsonify({
            "jobs": [],
            "count": 0,
            "daemon_unavailable": True,
            "message": "HTCondor daemon is not available."
        })
    limit = request.args.get("limit", current_app.config["MAX_HISTORY_RESULTS"], type=int)
    constraint = request.args.get("constraint", DEFAULT_CONSTRAINT)
    try:
        jobs = query_history(constraint=constraint, limit=limit)
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
            # Use proper osdf:/// URI format
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
    """Get log, stdout, and stderr file contents for a specific job proc.

    Query parameters:
        tail — Number of lines to return from the end of each file (default 500, 0 = all)
        download — If set to '1', returns a file download instead of JSON
        file — Which file to download: 'log', 'out', or 'err' (only used when download=1)
    """
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
    """Get complete job details, including all ClassAd attributes and file contents."""
    proc_id = request.args.get("proc", 0, type=int)
    tail = request.args.get("tail", 500, type=int)
    try:
        # Fetch ClassAd attributes
        jobs = query_jobs(constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}")
        if not jobs:
            jobs = query_history(
                constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
                limit=1,
            )
        job = jobs[0] if jobs else {}

        # Get log, stdout, and stderr file paths
        paths = get_job_log_file_paths(cluster_id, proc_id=proc_id)

        # Read file contents
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
# Submission history (from our database, not condor_history)
# ---------------------------------------------------------------------------


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