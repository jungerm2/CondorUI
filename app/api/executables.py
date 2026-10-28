"""Executable management endpoints."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from app.api import api_bp
from app.api.helpers import (
    _safe_path,
    build_zip_response,
)

logger = logging.getLogger(__name__)


@api_bp.route("/executables")
def list_executables():
    """List all uploaded executables (flat directory, no UUID paths)."""
    exec_dir = Path(current_app.config["EXECUTABLES_DIR"])
    exec_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for p in sorted(exec_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.is_file():
            stat = p.stat()
            files.append(
                {
                    "filename": p.name,
                    "size": stat.st_size,
                    "uploaded_at": stat.st_mtime,
                }
            )
    return jsonify({"executables": files})


@api_bp.route("/executables", methods=["POST"])
def upload_executable():
    """Upload an executable file (stored flat, no UUID path).

    Expects the raw file as the request body with:
      - Content-Type: application/octet-stream
      - X-Upload-Filename: original filename (required)
      - X-Overwrite: "true" to replace an existing executable with the same name
    """
    # Streamed uploads have a larger cap than ordinary JSON/form requests.
    request.max_content_length = current_app.config["MAX_UPLOAD_LENGTH"]
    original_filename = request.headers.get("X-Upload-Filename", "").strip()
    if not original_filename:
        return jsonify({"error": "Missing 'X-Upload-Filename' header"}), 400

    overwrite = request.headers.get("X-Overwrite", "").strip().lower() == "true"
    exec_dir = Path(current_app.config["EXECUTABLES_DIR"])
    exec_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename — no path separators
    filename = Path(original_filename).name
    dest = exec_dir / filename

    if dest.exists():
        if not overwrite:
            return jsonify({"error": f"Executable '{filename}' already exists"}), 409
        dest.unlink()

    # Save raw stream to disk
    with open(dest, "wb") as f:
        while True:
            chunk = request.stream.read(65536)
            if not chunk:
                break
            f.write(chunk)

    os.chmod(str(dest), 0o755)  # Make executable

    stat = dest.stat()
    return jsonify(
        {
            "filename": filename,
            "size": stat.st_size,
            "uploaded_at": stat.st_mtime,
        }
    ), 201


@api_bp.route("/executables/<path:filename>/download")
def download_executable(filename: str):
    """Download an uploaded executable file."""
    exec_dir = str(Path(current_app.config["EXECUTABLES_DIR"]).resolve())
    file_path = _safe_path(exec_dir, filename)

    if not file_path.exists():
        return jsonify({"error": "Executable not found"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to send executable %s", filename)
        return jsonify({"error": "Failed to download executable"}), 500


@api_bp.route("/executables/<path:filename>/preview")
def preview_executable(filename: str):
    """Serve an executable inline for the shared preview modal.

    Executables are scripts/text, so force a text mimetype — Flask would
    otherwise sniff them as ``application/x-sh`` and the modal would fall
    back to download for what is perfectly readable content.
    """
    exec_dir = str(Path(current_app.config["EXECUTABLES_DIR"]).resolve())
    file_path = _safe_path(exec_dir, filename)

    if not file_path.exists():
        return jsonify({"error": "Executable not found"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=False,
            mimetype="text/plain",
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to preview executable %s", filename)
        return jsonify({"error": "Failed to preview executable"}), 500


@api_bp.route("/executables/bulk-download", methods=["POST"])
def bulk_download_executables():
    """Download several executables as one zip archive.

    Request JSON: {"files": ["name", ...]}; archives download directly on
    the client instead of being re-zipped.
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    exec_dir = str(Path(current_app.config["EXECUTABLES_DIR"]).resolve())
    entries: list[tuple[str, Path]] = []
    for filename in data["files"]:
        if not isinstance(filename, str) or not filename.strip():
            continue
        entries.append((filename, _safe_path(exec_dir, filename)))
    if not entries:
        return jsonify({"error": "No valid files"}), 400

    try:
        bundled = build_zip_response(entries, download_name="executables.zip")
    except Exception:
        logger.exception("Failed to build bulk download")
        return jsonify({"error": "Failed to build bulk download"}), 500
    if bundled is None:
        return jsonify({"error": "Requested files are not available"}), 404
    return bundled[0]


@api_bp.route("/executables/<path:filename>", methods=["DELETE"])
def delete_executable(filename: str):
    """Delete an uploaded executable."""
    exec_dir = str(Path(current_app.config["EXECUTABLES_DIR"]).resolve())
    file_path = _safe_path(exec_dir, filename)

    if not file_path.exists():
        return jsonify({"error": "Executable not found"}), 404

    file_path.unlink()
    return jsonify({"message": f"Executable '{filename}' deleted"})
