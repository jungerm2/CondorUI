"""Container image management endpoints."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from app.api import api_bp
from app.api.helpers import (
    _find_existing_container_by_name,
    _osdf_uri,
    _remove_empty_parents,
    _safe_path,
    build_zip_response,
    container_display_name,
)
from app.utils import (
    save_uploaded_stream,
    scan_uuid_directories,
)

logger = logging.getLogger(__name__)


@api_bp.route("/containers", methods=["GET"])
def list_containers():
    """List all container images."""
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"containers": [], "count": 0})

    containers_dir = str(Path(osdf_root) / "containers")
    raw = scan_uuid_directories(containers_dir, file_filter=".sif")
    containers = []
    base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")
    for entry in raw:
        rel_name = entry["filename"]
        # Derive display name from filename (strip .sif)
        display_name = container_display_name(entry["original_name"])
        # Build the URI: OSDF_BASE_URI + absolute path to the .sif file
        file_path = str(Path(containers_dir) / rel_name)
        uri = _osdf_uri(base_uri, file_path)
        containers.append(
            {
                "filename": rel_name,
                "name": display_name,
                "source": f"file:{rel_name}",
                "uri": uri,
                "size": entry["size"],
                "created_at": entry["modified_at"],
            }
        )
    return jsonify({"containers": containers, "count": len(containers)})


def _prepare_pull(image_ref: str, name: str, overwrite: bool):
    """Shared validation/setup for the container pull endpoints.

    Returns ``(error, unique_name, dest_path)`` — *error* is a human-readable
    message string on failure (with ``unique_name``/``dest_path`` both None),
    or ``None`` on success.
    """
    if "://" not in image_ref:
        return (
            "Invalid image reference. Please include a scheme prefix (e.g., docker://...)",
            None,
            None,
        )

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return ("OSDF root path is not configured", None, None)

    containers_dir = Path(osdf_root) / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    # Check if a container with the same display name already exists
    existing = _find_existing_container_by_name(str(containers_dir), name)
    if existing:
        if not overwrite:
            return (f"Container '{name}' already exists", None, None)
        # Delete the existing entry
        existing_path = containers_dir / existing["filename"]
        if existing_path.exists():
            existing_path.unlink()
            _remove_empty_parents(existing_path.parent)

    # Generate a unique filename: uuid/safe_name.sif
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.lower())
    unique_name = f"{uuid.uuid4().hex}/{safe_name}.sif"
    dest_path = containers_dir / unique_name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return (None, unique_name, dest_path)


@api_bp.route("/containers/pull", methods=["POST"])
def pull_container():
    """Pull a Docker image and convert to Apptainer .sif.

    Request JSON:
    {
        "image": "docker://ubuntu:latest",
        "name": "Ubuntu Latest",
        "overwrite": false
    }
    """
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' in request body"}), 400

    image_ref = data["image"].strip()
    name = data.get("name", "").strip() or Path(image_ref).name
    overwrite = data.get("overwrite", False)

    error, unique_name, dest_path = _prepare_pull(image_ref, name, overwrite)
    if error:
        code = 409 if "already exists" in error else 400
        return jsonify({"error": error}), code

    try:
        # Run apptainer pull
        logger.info("Pulling container: %s -> %s", image_ref, dest_path)
        result = subprocess.run(  # noqa: PLW1510
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

        return jsonify(
            {
                "filename": unique_name,
                "name": name,
                "source": image_ref,
                "size": size,
                "created_at": dest_path.stat().st_mtime,
            }
        ), 201

    except subprocess.TimeoutExpired:
        return jsonify({"error": "apptainer pull timed out after 600 seconds"}), 500
    except FileNotFoundError:
        return jsonify(
            {
                "error": "apptainer command not found. Is Apptainer/Singularity installed?"
            }
        ), 500
    except Exception:
        logger.exception("Container pull failed")
        return jsonify({"error": "Container pull failed"}), 500


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
    overwrite = request.args.get("overwrite", "").strip().lower() == "true"

    error, unique_name, dest_path = _prepare_pull(image_ref, name, overwrite)
    if error:

        def err_gen():
            yield f"event: error\ndata: {error}\n\n"

        return Response(err_gen(), mimetype="text/event-stream")

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

            yield f"event: complete\ndata: {json.dumps({'filename': unique_name, 'name': name, 'source': image_ref, 'size': size, 'created_at': dest_path.stat().st_mtime})}\n\n"

        except FileNotFoundError:
            yield "event: error\ndata: apptainer command not found. Is Apptainer/Singularity installed?\n\n"
        except Exception:
            logger.exception("Container pull failed")
            yield "event: error\ndata: Container pull failed\n\n"

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
      - X-Overwrite: "true" to replace an existing container with the same name
    """
    original_filename = request.headers.get("X-Container-Filename", "").strip()
    if not original_filename:
        return jsonify({"error": "Missing 'X-Container-Filename' header"}), 400

    if not original_filename.lower().endswith(".sif"):
        return jsonify({"error": "Only .sif files are accepted"}), 400

    overwrite = request.headers.get("X-Overwrite", "").strip().lower() == "true"
    name = (
        request.headers.get("X-Container-Name", "").strip()
        or Path(original_filename).stem
    )

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    containers_dir = str(Path(osdf_root) / "containers")

    # Check if a container with the same display name already exists
    existing = _find_existing_container_by_name(containers_dir, name)
    if existing:
        if not overwrite:
            return jsonify({"error": f"Container '{name}' already exists"}), 409
        # Delete the existing entry
        existing_path = Path(containers_dir) / existing["filename"]
        if existing_path.exists():
            existing_path.unlink()
            _remove_empty_parents(existing_path.parent)

    try:
        unique_name, size = save_uploaded_stream(
            request.stream, containers_dir, original_filename, name=name
        )

        return jsonify(
            {
                "filename": unique_name,
                "name": name,
                "source": f"uploaded:{original_filename}",
                "size": size,
                "created_at": (Path(containers_dir) / unique_name).stat().st_mtime,
            }
        ), 201
    except Exception:
        logger.exception("Container upload failed")
        return jsonify({"error": "Container upload failed"}), 500


@api_bp.route("/containers/<path:filename>", methods=["PUT"])
def rename_container(filename: str):
    """Rename a container (display name only).

    Since the filesystem stores containers under UUID directories,
    "renaming" means updating the display name stored in the filename
    within the UUID directory.
    """
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Missing 'name' in request body"}), 400

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    file_path = _safe_path(osdf_root, "containers", filename)
    if not file_path.exists():
        return jsonify({"error": "Container not found"}), 404

    new_name = data["name"]
    safe_name = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in new_name.lower()
    )
    new_path = file_path.parent / f"{safe_name}.sif"

    if new_path.exists():
        return jsonify({"error": "A container with that name already exists"}), 409

    file_path.rename(new_path)

    new_rel_name = f"{file_path.parent.name}/{new_path.name}"
    stat = new_path.stat()

    return jsonify(
        {
            "filename": new_rel_name,
            "name": new_name,
            "source": f"file:{new_rel_name}",
            "size": stat.st_size,
            "created_at": stat.st_mtime,
        }
    )


@api_bp.route("/containers/<path:filename>/download")
def download_container(filename: str):
    """Download a container image file from disk."""
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    file_path = _safe_path(osdf_root, "containers", filename)
    if not file_path.exists():
        return jsonify({"error": "Container not found"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to send container %s", filename)
        return jsonify({"error": "Failed to download container"}), 500


@api_bp.route("/containers/<path:filename>/preview")
def preview_container(filename: str):
    """Serve a container image inline for the shared preview modal.

    ``.sif`` files are binary images the browser cannot render; the modal
    shows its fallback message instead without fetching the body.
    """
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    file_path = _safe_path(osdf_root, "containers", filename)
    if not file_path.exists():
        return jsonify({"error": "Container not found"}), 404

    try:
        return send_file(
            str(file_path),
            as_attachment=False,
            download_name=file_path.name,
        )
    except Exception:
        logger.exception("Failed to preview container %s", filename)
        return jsonify({"error": "Failed to preview container"}), 500


@api_bp.route("/containers/bulk-download", methods=["POST"])
def bulk_download_containers():
    """Download several container images as one zip archive.

    Request JSON: {"files": ["<uuid-dir>/<file>.sif", ...]}.  The client
    downloads containers directly, one file each, so this normally only
    sees non-archive selections.
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    entries: list[tuple[str, Path]] = []
    for filename in data["files"]:
        if not isinstance(filename, str) or not filename.strip():
            continue
        entries.append(
            (Path(filename).name, _safe_path(osdf_root, "containers", filename))
        )
    if not entries:
        return jsonify({"error": "No valid files"}), 400

    try:
        bundled = build_zip_response(entries, download_name="containers.zip")
    except Exception:
        logger.exception("Failed to build bulk download")
        return jsonify({"error": "Failed to build bulk download"}), 500
    if bundled is None:
        return jsonify({"error": "Requested files are not available"}), 404
    return bundled[0]


@api_bp.route("/containers/<path:filename>", methods=["DELETE"])
def delete_container(filename: str):
    """Delete a container image from disk."""
    osdf_root = current_app.config.get("OSDF_ROOT_PATH", "")
    if not osdf_root:
        return jsonify({"error": "OSDF root path is not configured"}), 400

    file_path = _safe_path(osdf_root, "containers", filename)
    if not file_path.exists():
        return jsonify({"error": "Container not found"}), 404

    file_path.unlink()
    _remove_empty_parents(file_path.parent)

    return jsonify({"message": f"Container '{filename}' deleted"})
