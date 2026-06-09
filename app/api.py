"""REST API blueprint for HTCondor job management."""

from __future__ import annotations

import json
import logging
import os
import shutil

from flask import Blueprint, current_app, jsonify, request

from app import db
from app.condor import (
    DEFAULT_CONSTRAINT,
    act_on_job,
    get_job_log,
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
# Job queries
# ---------------------------------------------------------------------------


@api_bp.route("/jobs")
def list_jobs():
    """List active jobs, with optional filters."""
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
        jobs = query_jobs(constraint=constraint)
        return jsonify({"jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:cluster_id>")
def get_cluster(cluster_id: int):
    """Get all procs for a specific cluster."""
    try:
        jobs = query_jobs(constraint=f"ClusterId == {cluster_id}")
        if not jobs:
            # Check history
            jobs = query_history(
                constraint=f"ClusterId == {cluster_id}", limit=1000
            )
        return jsonify({"cluster_id": cluster_id, "jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/history")
def list_history():
    """List completed jobs from condor_history."""
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
    """Submit a job from a JSON submit description.

    Expected JSON body:
    {
        "name": "My Job",
        "submit": { "executable": "/bin/sleep", "arguments": "60", ... },
        "count": 1,
        "itemdata": [{"var": "val"}, ...]  // optional
    }
    """
    data = request.get_json()
    if not data or "submit" not in data:
        return jsonify({"error": "Missing 'submit' in request body"}), 400

    submit_dict = data["submit"]
    count = data.get("count", 1)
    itemdata = data.get("itemdata")
    name = data.get("name", "Untitled Job")

    try:
        if itemdata:
            cluster_id = submit_job(submit_dict, count=len(itemdata), itemdata=itemdata)
            num_procs = len(itemdata)
        else:
            cluster_id = submit_job(submit_dict, count=count)
            num_procs = count

        # Record in database
        submission = JobSubmission(
            cluster_id=cluster_id,
            name=name,
            submit_description=json.dumps(submit_dict),
            num_procs=num_procs,
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
        cluster_id, num_procs = submit_from_file(content)

        submission = JobSubmission(
            cluster_id=cluster_id,
            name=name,
            submit_description=content,
            num_procs=num_procs,
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
    """Upload files, optionally staging them to the OSDF cache directory.

    Files are saved to the local upload dir.  If OSDF_STAGING_PATH is
    configured, they are additionally copied there so that HTCondor can
    fetch them via OSDF.

    Returns the list of saved file paths (both local and OSDF).
    """
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
            entry["osdf_path"] = osdf_dest

        saved.append(entry)

    return jsonify({"uploaded": saved, "count": len(saved)}), 201


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


@api_bp.route("/jobs/<job_id>/hold", methods=["POST"])
def hold_job(job_id: str):
    """Hold a job."""
    try:
        result = act_on_job("hold", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<job_id>/release", methods=["POST"])
def release_job(job_id: str):
    """Release a held job."""
    try:
        result = act_on_job("release", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<job_id>", methods=["DELETE"])
def remove_job(job_id: str):
    """Remove a job."""
    try:
        result = act_on_job("remove", job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Job logs
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
