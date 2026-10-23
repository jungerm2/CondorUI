"""Job output file endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import jsonify, request, send_file

from app.api import api_bp
from app.api.helpers import (
    _safe_path,
    build_zip_response,
)
from app.models import JobSubmission

logger = logging.getLogger(__name__)


def _output_file_entry(f: Path, sub: JobSubmission, meta: dict) -> dict:
    """Build a listing entry for one output file."""
    stat = f.stat()
    return {
        "filename": f.name,
        "path": str(f),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "cluster_id": sub.cluster_id,
        "job_name": meta["name"],
        "command": meta["command"],
    }


@api_bp.route("/output-files")
def list_output_files():
    """List all output files from completed jobs.

    Uses ``output_destination`` and ``transfer_output_remaps`` stored in the
    JobSubmission record to locate output files.  For jobs with
    ``output_destination`` set, scans that directory.  For jobs with
    ``transfer_output_remaps``, parses the remap rules and lists the
    destination files.

    Builds a cluster_id → {name, command} lookup in a single query
    to avoid N+1 queries when enriching each output file entry.
    """
    # Single query: load all submissions with output_destination set
    submissions = JobSubmission.query.filter(
        JobSubmission.output_destination.isnot(None)
    ).all()

    # Build cluster_id → metadata lookup (in-memory, no extra queries)
    cluster_meta: dict[int, dict[str, str]] = {}
    for sub in submissions:
        command = ""
        try:
            desc_text = sub.submit_description or ""
            if desc_text.strip().startswith("{"):
                desc = json.loads(desc_text)
                command = desc.get("shell") or desc.get("executable", "")
        except json.JSONDecodeError, AttributeError:
            pass
        cluster_meta[sub.cluster_id] = {
            "name": sub.name,
            "command": command,
        }

    output_files = []
    try:
        for sub in submissions:
            meta = cluster_meta.get(sub.cluster_id, {"name": sub.name, "command": ""})

            # 1. Scan output_destination directory
            if sub.output_destination:
                dest_path = Path(sub.output_destination)
                if dest_path.exists():
                    for f in dest_path.iterdir():
                        if f.is_file():
                            output_files.append(_output_file_entry(f, sub, meta))

            # 2. Parse transfer_output_remaps for additional files
            if sub.transfer_output_remaps:
                # Format: "src1 = dest1; src2 = dest2"
                remaps = sub.transfer_output_remaps
                for part in remaps.split(";"):
                    part = part.strip()
                    if "=" in part:
                        _src, dest = part.split("=", 1)
                        dest = dest.strip()
                        if dest and Path(dest).exists():
                            output_files.append(
                                _output_file_entry(Path(dest), sub, meta)
                            )

        # Sort by modified_at descending
        output_files.sort(key=lambda x: x.get("modified_at", 0), reverse=True)

        return jsonify({"output_files": output_files, "count": len(output_files)})
    except Exception:
        logger.exception("Failed to list output files")
        return jsonify({"error": "Failed to list output files"}), 500


@api_bp.route("/output-files/preview/<int:cluster_id>/<path:filename>")
def preview_output_file(cluster_id: int, filename: str):
    """Serve an output file inline (browser-native preview).

    Images render in <img>, text in <pre>; other types fall back to
    downloading.  Same safety rules as the download endpoint.
    """
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission or not submission.output_destination:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _safe_path(submission.output_destination, filename)

    if not file_path.exists():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=False,
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to preview output file")
        return jsonify({"error": "Failed to preview output file"}), 500


@api_bp.route("/output-files/bulk-download", methods=["POST"])
def bulk_download_output_files():
    """Download several output files as one zip archive.

    Request JSON: {"files": [{"cluster_id": 123, "filename": "a.png"}, ...]}
    Name collisions across clusters are resolved by prefixing the cluster id.
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    # Resolve every requested file up front (single submissions query).
    by_cluster: dict[int, list[str]] = {}
    for item in data["files"]:
        cid = item.get("cluster_id")
        fname = str(item.get("filename") or "")
        if cid is None or not fname:
            continue
        by_cluster.setdefault(int(cid), []).append(fname)
    if not by_cluster:
        return jsonify({"error": "No valid files"}), 400

    subs = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(list(by_cluster.keys()))
    ).all()
    dest_by_cluster = {s.cluster_id: s.output_destination for s in subs}

    skipped: list[str] = []
    entries: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    for cid, filenames in by_cluster.items():
        base = dest_by_cluster.get(cid)
        if not base:
            skipped.extend(f"{cid}/{f}" for f in filenames)
            continue
        for fname in filenames:
            try:
                file_path = _safe_path(base, fname)
            except Exception:  # noqa: BLE001 — traversal → skip
                skipped.append(f"{cid}/{fname}")
                continue
            # Flat archive; same-named files from different clusters get a
            # `{cid}-` prefix so the shared builder's collision handling
            # stays unambiguous.
            arcname = (
                f"{cid}-{file_path.name}"
                if file_path.name in seen_names
                else file_path.name
            )
            seen_names.add(arcname)
            entries.append((arcname, file_path))

    try:
        bundled = build_zip_response(entries, download_name="output_files.zip")
    except Exception:
        logger.exception("Failed to build bulk download")
        return jsonify({"error": "Failed to build bulk download"}), 500
    if bundled is None:
        return jsonify({"error": "Requested files are not available"}), 404
    resp, _bundled_skipped = bundled
    if skipped:
        existing = resp.headers.get("X-Skipped-Files")
        combined = ",".join([*skipped, existing]) if existing else ",".join(skipped)
        resp.headers["X-Skipped-Files"] = ",".join(combined.split(",")[:20])
    return resp


@api_bp.route("/output-files/delete-bulk", methods=["DELETE"])
def delete_output_files_bulk():
    """Delete several output files in one request.

    Request JSON: {"files": [{"cluster_id": 123, "filename": "a.png"}, ...]}
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    by_cluster: dict[int, list[str]] = {}
    for item in data["files"]:
        cid = item.get("cluster_id")
        fname = str(item.get("filename") or "")
        if cid is None or not fname:
            continue
        by_cluster.setdefault(int(cid), []).append(fname)
    if not by_cluster:
        return jsonify({"error": "No valid files"}), 400

    subs = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(list(by_cluster.keys()))
    ).all()
    dest_by_cluster = {s.cluster_id: s.output_destination for s in subs}

    deleted: list[str] = []
    failed: list[dict] = []
    try:
        for cid, filenames in by_cluster.items():
            base = dest_by_cluster.get(cid)
            for fname in filenames:
                if not base:
                    failed.append(
                        {"filename": f"{cid}/{fname}", "error": "no output destination"}
                    )
                    continue
                try:
                    file_path = _safe_path(base, fname)
                except Exception:  # noqa: BLE001 — traversal → fail that file
                    failed.append(
                        {"filename": f"{cid}/{fname}", "error": "invalid path"}
                    )
                    continue
                if not file_path.exists():
                    failed.append({"filename": f"{cid}/{fname}", "error": "not found"})
                    continue
                try:
                    file_path.unlink()
                    deleted.append(f"{cid}/{fname}")
                except Exception:
                    logger.exception("Failed to delete output file %s/%s", cid, fname)
                    failed.append(
                        {"filename": f"{cid}/{fname}", "error": "delete failed"}
                    )

        message = f"Deleted {len(deleted)} file(s)"
        if failed:
            message += f", {len(failed)} failed"
        return jsonify({"message": message, "deleted": deleted, "failed": failed})
    except Exception:
        logger.exception("Failed to bulk delete output files")
        return jsonify({"error": "Failed to delete files"}), 500


@api_bp.route("/output-files/download/<int:cluster_id>/<path:filename>")
def download_output_file(cluster_id: int, filename: str):
    """Download a specific output file for a given job.

    Uses ``output_destination`` from the JobSubmission record to resolve
    the file path.
    """
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission or not submission.output_destination:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _safe_path(submission.output_destination, filename)

    if not file_path.exists():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to send output file")
        return jsonify({"error": "Failed to send output file"}), 500


@api_bp.route(
    "/output-files/delete/<int:cluster_id>/<path:filename>", methods=["DELETE"]
)
def delete_output_file(cluster_id: int, filename: str):
    """Delete an output file for a given job."""
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission or not submission.output_destination:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _safe_path(submission.output_destination, filename)

    if not file_path.exists():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        file_path.unlink()
        return jsonify({"message": f"Deleted output file: {filename}"})
    except Exception:
        logger.exception("Failed to delete output file")
        return jsonify({"error": "Failed to delete output file"}), 500
