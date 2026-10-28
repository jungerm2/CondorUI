"""Input file management endpoints."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from flask import abort, current_app, jsonify, request, send_file

from app.api import api_bp
from app.api.helpers import (
    _find_existing_file_by_original_name,
    _osdf_uri,
    _remove_empty_parents,
    _safe_path,
    build_zip_response,
)
from app.utils import (
    safe_filename,
    save_uploaded_stream,
    scan_uuid_directories,
)

logger = logging.getLogger(__name__)


def _build_file_entry(
    rel_name: str,
    original_name: str,
    file_path: Path,
    stat: os.stat_result,
) -> dict:
    """Build a file dict for the frontend, checking both local and OSDF locations.

    A file may be in either UPLOAD_DIR (local) or OSDF_ROOT_PATH/uploads/
    (staged).  This function checks both locations and sets the appropriate
    fields.
    """
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    osdf_path = None
    if osdf_root:
        candidate = Path(osdf_root) / "uploads" / rel_name
        if candidate.exists():
            osdf_path = str(candidate)

    base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")
    if osdf_path:
        uri = _osdf_uri(base_uri, osdf_path)
    else:
        uri = str(file_path)

    return {
        "filename": rel_name,
        "original_name": original_name,
        "local_path": str(file_path) if not osdf_path else None,
        "osdf_path": osdf_path,
        "uri": uri,
        "size": stat.st_size,
        "uploaded_at": stat.st_mtime,
    }


@api_bp.route("/files", methods=["GET"])
def list_files():
    """List all uploaded files.

    Scans both UPLOAD_DIR and OSDF_ROOT_PATH/uploads/ for files, merging
    the results.  Files in OSDF are marked as staged; files in UPLOAD_DIR
    are marked as local.  If a file exists in both locations (shouldn't
    happen in normal operation), the OSDF version takes precedence.
    """
    upload_dir = current_app.config["UPLOAD_DIR"]
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")

    # Build a set of seen filenames to avoid duplicates
    seen = set()
    files = []

    # 1. Scan OSDF uploads directory first (takes precedence)
    if osdf_root:
        osdf_uploads = str(Path(osdf_root) / "uploads")
        for entry in scan_uuid_directories(osdf_uploads):
            rel_name = entry["filename"]
            seen.add(rel_name)
            file_path = Path(osdf_uploads) / rel_name
            files.append(
                _build_file_entry(
                    rel_name,
                    entry["original_name"],
                    file_path,
                    file_path.stat(),
                )
            )

    # 2. Scan local upload directory for files not already in OSDF
    for entry in scan_uuid_directories(upload_dir):
        rel_name = entry["filename"]
        if rel_name in seen:
            continue
        seen.add(rel_name)
        file_path = Path(upload_dir) / rel_name
        files.append(
            _build_file_entry(
                rel_name,
                entry["original_name"],
                file_path,
                file_path.stat(),
            )
        )

    # Sort by uploaded_at descending
    files.sort(key=lambda f: f.get("uploaded_at", 0), reverse=True)

    return jsonify({"files": files, "count": len(files)})


@api_bp.route("/files", methods=["POST"])
def upload_files():
    """Upload a file to the filesystem.

    Expects the raw file as the request body with:
      - Content-Type: application/octet-stream
      - X-Upload-Filename: original filename (required)
      - X-Overwrite: "true" to replace an existing file with the same name
    """
    # Streamed uploads have a larger cap than ordinary JSON/form requests.
    request.max_content_length = current_app.config["MAX_UPLOAD_LENGTH"]
    original_filename = request.headers.get("X-Upload-Filename", "").strip()
    if not original_filename:
        return jsonify({"error": "Missing 'X-Upload-Filename' header"}), 400

    # Reject unusable names early (e.g., "../..") — save_uploaded_stream
    # also sanitizes, but a clean 400 beats a generic 500.
    try:
        safe_filename(original_filename)
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400

    overwrite = request.headers.get("X-Overwrite", "").strip().lower() == "true"
    upload_dir = current_app.config["UPLOAD_DIR"]

    # Check if a file with the same original_name already exists
    existing = _find_existing_file_by_original_name(upload_dir, original_filename)
    if existing:
        if not overwrite:
            return jsonify({"error": f"File '{original_filename}' already exists"}), 409
        # Delete the existing entry (UUID directory + file)
        existing_path = Path(upload_dir) / existing["filename"]
        if existing_path.exists():
            existing_path.unlink()
            _remove_empty_parents(existing_path.parent)

    try:
        unique_name, size = save_uploaded_stream(
            request.stream, upload_dir, original_filename
        )

        upload_path = Path(upload_dir) / unique_name

        return jsonify(
            {
                "filename": unique_name,
                "original_name": original_filename,
                "local_path": str(upload_path),
                "osdf_path": None,
                "uri": str(upload_path),
                "size": size,
                "uploaded_at": upload_path.stat().st_mtime,
            }
        ), 201
    except Exception:
        logger.exception("File upload failed")
        return jsonify({"error": "File upload failed"}), 500


def _resolve_upload_path(filename: str) -> Path:
    """Resolve an input filename from the local upload dir or OSDF staging.

    Staged files are moved, not copied, so the local copy may legitimately
    be gone.  Aborts with 404 when neither location has the file.
    """
    upload_dir = current_app.config["UPLOAD_DIR"]
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")

    file_path = _safe_path(upload_dir, filename)
    if not file_path.exists() and osdf_root:
        file_path = _safe_path(osdf_root, "uploads", filename)
    if not file_path.exists():
        abort(404, description="File not found")
    return file_path


@api_bp.route("/files/<path:filename>/download")
def download_file(filename: str):
    """Download an input file, from the local upload dir or OSDF staging."""
    file_path = _resolve_upload_path(filename)

    try:
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=Path(filename).name,
        )
    except Exception:
        logger.exception("Failed to send file %s", filename)
        return jsonify({"error": "Failed to download file"}), 500


@api_bp.route("/files/<path:filename>/preview")
def preview_file(filename: str):
    """Serve an input file inline for the shared preview modal."""
    file_path = _resolve_upload_path(filename)

    try:
        return send_file(
            str(file_path),
            as_attachment=False,
            download_name=Path(filename).name,
        )
    except Exception:
        logger.exception("Failed to preview file %s", filename)
        return jsonify({"error": "Failed to preview file"}), 500


@api_bp.route("/files/bulk-download", methods=["POST"])
def bulk_download_files():
    """Download several input files as one zip archive.

    Request JSON: {"files": ["<uuid-dir>/<file>", ...]}.  The client sends
    only non-archive selections; files already stored as archives (or
    container images) download directly instead of being re-zipped.
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    entries: list[tuple[str, Path]] = []
    for filename in data["files"]:
        if not isinstance(filename, str) or not filename.strip():
            continue
        entries.append((Path(filename).name, _resolve_upload_path(filename)))
    if not entries:
        return jsonify({"error": "No valid files"}), 400

    try:
        bundled = build_zip_response(entries, download_name="input_files.zip")
    except Exception:
        logger.exception("Failed to build bulk download")
        return jsonify({"error": "Failed to build bulk download"}), 500
    if bundled is None:
        return jsonify({"error": "Requested files are not available"}), 404
    return bundled[0]


@api_bp.route("/files/<path:filename>", methods=["PUT"])
def rename_file(filename: str):
    """Rename an uploaded file (display name only).

    Since the filesystem stores files under UUID directories, "renaming"
    means updating the original filename within the UUID directory.
    """
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "Missing 'filename' in request body"}), 400

    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = _safe_path(upload_dir, filename)

    # Files may live in the local upload dir or the OSDF staging area
    # (mirrors delete_file's dual-location behavior).
    staged = False
    if not file_path.exists():
        osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
        if not osdf_root:
            return jsonify({"error": "File not found"}), 404
        file_path = _safe_path(osdf_root, "uploads", filename)
        staged = True

    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    # The new name must be a single, harmless path component — it is
    # user-controlled JSON and previously allowed arbitrary write targets.
    try:
        new_name = safe_filename(data["filename"])
    except ValueError:
        return jsonify({"error": "Invalid filename"}), 400
    new_path = file_path.parent / new_name

    if new_path.exists():
        return jsonify({"error": "A file with that name already exists"}), 409

    file_path.rename(new_path)

    new_rel_name = f"{file_path.parent.name}/{new_name}"
    stat = new_path.stat()

    base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")
    osdf_path = str(new_path) if staged else None
    uri = _osdf_uri(base_uri, new_path) if staged else str(new_path)

    return jsonify(
        {
            "filename": new_rel_name,
            "original_name": new_name,
            "local_path": None if staged else str(new_path),
            "osdf_path": osdf_path,
            "uri": uri,
            "size": stat.st_size,
            "uploaded_at": stat.st_mtime,
        }
    )


@api_bp.route("/files/<path:filename>", methods=["DELETE"])
def delete_file(filename: str):
    """Delete an uploaded file from disk/OSDF."""
    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = _safe_path(upload_dir, filename)

    # Check local path
    deleted_local = False
    if file_path.exists():
        file_path.unlink()
        _remove_empty_parents(file_path.parent)
        deleted_local = True

    # Check OSDF path
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    osdf_path = None
    deleted_osdf = False
    if osdf_root:
        osdf_path = _safe_path(osdf_root, "uploads", filename)
        if osdf_path.exists():
            osdf_path.unlink()
            _remove_empty_parents(osdf_path.parent)
            deleted_osdf = True

    if not deleted_local and not deleted_osdf:
        return jsonify({"error": "File not found"}), 404

    return jsonify({"message": f"File '{filename}' deleted"})


@api_bp.route("/files/<path:filename>/stage", methods=["POST"])
def stage_file(filename: str):
    """Move a file to the OSDF uploads subdirectory."""
    upload_dir = current_app.config["UPLOAD_DIR"]
    file_path = _safe_path(upload_dir, filename)

    if not file_path.exists():
        return jsonify({"error": "Local file not found on disk"}), 404

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    # Check if already staged
    osdf_dest = _safe_path(osdf_root, "uploads", filename)
    if osdf_dest.exists():
        return jsonify({"error": "File is already staged to OSDF"}), 400

    osdf_dest.parent.mkdir(parents=True, exist_ok=True)

    # Move the file (not copy) — only one copy exists
    shutil.move(str(file_path), str(osdf_dest))

    # Clean up empty parent directories from the source location
    _remove_empty_parents(file_path.parent)

    stat = osdf_dest.stat()
    base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")

    return jsonify(
        {
            "filename": filename,
            "original_name": file_path.name,
            "local_path": None,
            "osdf_path": str(osdf_dest),
            "uri": _osdf_uri(base_uri, osdf_dest),
            "size": stat.st_size,
            "uploaded_at": stat.st_mtime,
        }
    )


@api_bp.route("/files/<path:filename>/unstage", methods=["POST"])
def unstage_file(filename: str):
    """Move a staged (OSDF) file back to the local upload directory."""
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    osdf_path = _safe_path(osdf_root, "uploads", filename)
    if not osdf_path.exists():
        return jsonify({"error": "OSDF file not found on disk"}), 404

    upload_dir = current_app.config["UPLOAD_DIR"]
    local_dest = _safe_path(upload_dir, filename)
    local_dest.parent.mkdir(parents=True, exist_ok=True)

    # Move the file back
    shutil.move(str(osdf_path), str(local_dest))

    # Clean up empty parent directories from the OSDF source location
    _remove_empty_parents(osdf_path.parent)

    stat = local_dest.stat()

    return jsonify(
        {
            "filename": filename,
            "original_name": local_dest.name,
            "local_path": str(local_dest),
            "osdf_path": None,
            "uri": str(local_dest),
            "size": stat.st_size,
            "uploaded_at": stat.st_mtime,
        }
    )
