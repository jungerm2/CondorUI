"""Job query and action endpoints (hold/release/remove, logs, details, qedit)."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, request, send_file

from app import api as _api
from app import db
from app.api import api_bp
from app.api.history import _build_job_entry
from app.condor import (
    DEFAULT_CONSTRAINT,
    act_on_job,
    get_job_file_content,
    get_job_log,
    get_job_log_file_paths,
    qedit_job,
    query_history,
    query_jobs,
)
from app.models import JobSubmission
from app.utils import (
    resolve_commands,
)

logger = logging.getLogger(__name__)


@api_bp.route("/jobs")
def list_jobs():
    """List active jobs, with optional filters and pagination."""
    if not _api.daemon_available():
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

        # Resolve shell & executable commands to original values from the DB
        resolve_commands(paginated)

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
    except Exception:
        logger.exception("Failed to list jobs")
        return jsonify({"error": "Failed to list jobs"}), 500


@api_bp.route("/jobs/<int:cluster_id>")
def get_cluster(cluster_id):
    """Get all procs for a specific cluster."""
    if not _api.daemon_available():
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
    except Exception:
        logger.exception("Failed to get cluster %s", cluster_id)
        return jsonify({"error": "Failed to get cluster"}), 500


@api_bp.route("/jobs/<job_id>/hold", methods=["POST"])
def hold_job(job_id):
    """Hold a job."""
    try:
        result = act_on_job("hold", job_id)
        return jsonify(result)
    except Exception:
        logger.exception("Failed to hold job %s", job_id)
        return jsonify({"error": "Failed to hold job"}), 500


@api_bp.route("/jobs/<job_id>/release", methods=["POST"])
def release_job(job_id):
    """Release a held job."""
    try:
        result = act_on_job("release", job_id)
        return jsonify(result)
    except Exception:
        logger.exception("Failed to release job %s", job_id)
        return jsonify({"error": "Failed to release job"}), 500


def _act_on_clusters(action: str):
    """Apply a schedd *action* (hold/release) to a list of clusters.

    Uses a single schedd.act() call per cluster (constraint-based) to act on
    all procs in the cluster at once, rather than one API call per proc.

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
            result = act_on_job(action, f"ClusterId == {cid}")
            results.append({"cluster_id": cid, "success": True, "result": str(result)})
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to %s cluster %d: %s", action, cid, e)
            results.append(
                {
                    "cluster_id": cid,
                    "success": False,
                    "error": f"Failed to {action} cluster",
                }
            )

    return jsonify({"results": results, "count": len(results)})


@api_bp.route("/clusters/hold", methods=["POST"])
def hold_clusters():
    """Hold all jobs in one or more clusters."""
    return _act_on_clusters("hold")


@api_bp.route("/clusters/release", methods=["POST"])
def release_clusters():
    """Release all held jobs in one or more clusters."""
    return _act_on_clusters("release")


@api_bp.route("/jobs/<job_id>", methods=["DELETE"])
def remove_job(job_id):
    """Remove a job from the schedd, DB, and delete its log/out/err files."""
    try:
        # Parse cluster_id from job_id (format: "<clusterId>.<procId>" or just "<clusterId>")
        cluster_id = int(job_id.split(".")[0])

        # Ensure a clean session state
        db.session.rollback()

        # 1. Remove from schedd
        try:
            act_on_job("remove", job_id)
        except Exception:  # noqa: BLE001, S110
            pass  # Job may already be gone from schedd

        # 2. Delete from local DB and remove log/out/err files
        submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        if submission:
            for path_attr in ("log_path", "out_path", "err_path"):
                file_path = getattr(submission, path_attr, None)
                if file_path and Path(file_path).exists():
                    Path(file_path).unlink()
            db.session.delete(submission)
            db.session.commit()

        return jsonify({"message": f"Job {job_id} removed"})
    except Exception:
        db.session.rollback()
        logger.exception("Failed to remove job %s", job_id)
        return jsonify({"error": "Failed to remove job"}), 500


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
    except Exception:
        logger.exception("Failed to get log for cluster %s", cluster_id)
        return jsonify({"error": "Failed to get job log"}), 500


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
    except Exception:
        logger.exception("Failed to get files for cluster %s", cluster_id)
        return jsonify({"error": "Failed to get job files"}), 500


@api_bp.route("/jobs/<int:cluster_id>/details")
def job_details(cluster_id: int):
    """Get complete job details."""
    proc_id = request.args.get("proc", 0, type=int)
    tail = request.args.get("tail", 500, type=int)
    try:
        # 1. Try the active schedd first (fast for running jobs).
        #    A schedd outage degrades to the DB/history path below.
        try:
            jobs = query_jobs(
                constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}"
            )
        except Exception:  # noqa: BLE001
            logger.warning("Schedd query failed for cluster %d details", cluster_id)
            jobs = []
        job = jobs[0] if jobs else {}

        # 2. If not found in active queue, try the local DB first (fast, avoids slow condor_history)
        if not job:
            submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
            if submission:
                # Build a synthetic job record from the local DB submission
                # (shared synthesizer with the history endpoint), then fill
                # completion facts from condor_history when it still knows
                # the job — completion date, wall times, exit code.
                job = _build_job_entry(submission, proc_id)
                if _api.daemon_available():
                    try:
                        hist_rows = query_history(
                            constraint=(
                                f"ClusterId == {cluster_id} && ProcId == {proc_id}"
                            ),
                            limit=1,
                        )
                    except Exception:  # noqa: BLE001
                        hist_rows = []
                    if hist_rows:
                        for key, val in hist_rows[0].items():
                            if job.get(key) in (None, 0, "") and val is not None:
                                job[key] = val
            else:
                # 3. Last resort: query condor_history (slow, but necessary for jobs
                #    submitted outside the web UI)
                jobs = query_history(
                    constraint=f"ClusterId == {cluster_id} && ProcId == {proc_id}",
                    limit=1,
                )
                job = jobs[0] if jobs else {}

        # Resolve shell & executable commands to original values from the DB
        submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
        submission_name = submission.name if submission else "Job Subbed Outside Web UI"

        if job and submission:
            resolve_commands([job])

        # 4. Resolve log file paths using get_job_log_file_paths()
        #    (DB stored paths → ClassAd query → empty)
        paths = get_job_log_file_paths(cluster_id, proc_id)

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
    except Exception:
        logger.exception("Failed to get details for cluster %s", cluster_id)
        return jsonify({"error": "Failed to get job details"}), 500


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

    # Use `is None` checks — legitimate falsy values (e.g., 0 or "") must pass
    if cluster_id is None or attr is None or value is None:
        return jsonify(
            {"error": "Missing required fields: cluster_id, attr, value"}
        ), 400

    try:
        result = qedit_job(cluster_id, proc_id, attr, value)
        return jsonify(result)
    except Exception:
        logger.exception("Failed to qedit cluster %s", cluster_id)
        return jsonify({"error": "Failed to edit job attribute"}), 500
