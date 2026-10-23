"""Job submission endpoints."""

from __future__ import annotations

import logging

from flask import jsonify, request

from app.api import api_bp
from app.condor import (
    submit_from_file,
    submit_job,
)

logger = logging.getLogger(__name__)


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

    # The "queue" key must NOT be in the submit dict — HTCondor's Python
    # bindings reject it with: "the queue statement can not be specified
    # in a dictionary".  Pop it out and pass as a separate queue_stmt
    # argument to submit_job() instead.
    queue_stmt = str(submit_dict.pop("queue", count)) if count else None

    try:
        if itemdata:
            cluster_id, num_procs = submit_job(
                submit_dict,
                count=len(itemdata),
                itemdata=itemdata,
                name=name,
                queue_stmt=queue_stmt,
            )
        else:
            cluster_id, num_procs = submit_job(
                submit_dict, count=count, name=name, queue_stmt=queue_stmt
            )

        return jsonify(
            {
                "cluster_id": cluster_id,
                "num_procs": num_procs,
                "message": f"Submitted cluster {cluster_id} with {num_procs} proc(s)",
            }
        ), 201
    except Exception:
        logger.exception("Job submission failed")
        return jsonify({"error": "Job submission failed"}), 500


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
    except Exception:
        logger.exception("Job submission from file failed")
        return jsonify({"error": "Job submission failed"}), 500
