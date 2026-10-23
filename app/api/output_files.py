"""Job output file endpoints."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from flask import abort, current_app, jsonify, request, send_file
from sqlalchemy import or_

from app.api import api_bp
from app.api.helpers import (
    _safe_path,
    build_zip_response,
)
from app.models import JobSubmission

logger = logging.getLogger(__name__)


def _local_output_path(value: str) -> Path | None:
    """Map a submit-side output path or URI to a local filesystem path.

    ``output_directory`` is normally a plain path, but it can also be a
    ``file://`` or ``osdf://`` URI.  The OSDF case is mapped back through
    ``OSDF_ROOT_PATH`` when the URI points at the local origin.
    """
    value = value.strip()
    if not value:
        return None
    if "://" not in value:
        return Path(value).expanduser()

    parsed = urlsplit(value)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).expanduser() if parsed.path else None
    if parsed.scheme != "osdf":
        return None

    path = unquote(parsed.path)
    if not path:
        return None

    base_uri = str(current_app.config.get("OSDF_BASE_URI") or "")
    if "://" in base_uri:
        base_path = urlsplit(base_uri).path.rstrip("/")
        if base_path and (path == base_path or path.startswith(base_path + "/")):
            path = path[len(base_path) :] or "/"

    osdf_root = str(current_app.config.get("OSDF_ROOT_PATH") or "").rstrip("/")
    if osdf_root:
        idx = path.find(osdf_root)
        if idx >= 0:
            path = path[idx:]

    if not path.startswith("/"):
        path = "/" + path
    return Path(path)


def _output_root(sub: JobSubmission) -> Path | None:
    """Return the local directory HTCondor transferred this job's outputs to."""
    if not sub.output_destination:
        return None
    root = _local_output_path(sub.output_destination)
    return root.resolve() if root else None


def _proc_sibling_roots(root: Path, num_procs: int) -> list[tuple[int, Path]]:
    """Find per-proc output directories beside *root*.

    ``output_directory`` often expands ``$(JobId)`` or ``$(ProcId)``, so the
    submission only records proc 0's path.  Recover sibling proc directories
    when the final path component is recognizably proc 0.
    """
    if num_procs <= 1 or not root.parent.is_dir():
        return []

    name = root.name
    if name == "0":
        prefix, width = "", 0
    elif name.isdigit() and set(name) == {"0"} and len(name) <= 5:
        prefix, width = "", len(name)
    elif name.endswith(".0"):
        prefix, width = name[:-1], 0
    elif name.startswith("proc") and name[4:].isdigit() and int(name[4:]) == 0:
        prefix, width = "proc", 0
    else:
        return []

    siblings: list[tuple[int, Path]] = []
    try:
        entries = sorted(root.parent.iterdir())
    except OSError:
        return []

    for child in entries:
        if child == root or not child.is_dir() or child.is_symlink():
            continue
        if prefix:
            if not child.name.startswith(prefix):
                continue
            digits = child.name[len(prefix) :]
        else:
            digits = child.name
        if not digits.isdigit() or (width and len(digits) != width):
            continue
        proc_id = int(digits)
        if 0 < proc_id < num_procs:
            siblings.append((proc_id, child.resolve()))
    return siblings


def _scan_roots(sub: JobSubmission) -> list[tuple[int, Path]]:
    """Return every local output root for *sub*, keyed by proc id."""
    root = _output_root(sub)
    if root is None:
        return []
    return [(0, root), *_proc_sibling_roots(root, sub.num_procs or 0)]


def _iter_files(root: Path):
    """Yield regular files below *root* without following directory symlinks."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if not Path(dirpath, name).is_symlink()
        ]
        for name in filenames:
            path = Path(dirpath, name)
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            yield path


def _output_file_entry(
    f: Path,
    root: Path,
    sub: JobSubmission,
    meta: dict,
    proc_id: int,
) -> dict | None:
    """Build a listing entry for one output file."""
    try:
        stat = f.stat()
        filename = f.relative_to(root).as_posix()
    except OSError, ValueError:
        return None
    return {
        "filename": filename,
        "path": str(f),
        "root": str(root),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "cluster_id": sub.cluster_id,
        "proc_id": proc_id,
        "job_name": meta["name"],
        "command": meta["command"],
    }


def _remap_destinations(sub: JobSubmission):
    """Yield the destination side of each ``transfer_output_remaps`` rule."""
    for part in (sub.transfer_output_remaps or "").split(";"):
        if "=" not in part:
            continue
        _src, dest = part.split("=", 1)
        dest = dest.strip().strip('"').strip("'")
        if dest:
            yield dest


def _resolve_remap(dest: str, output_root: Path | None) -> Path | None:
    """Resolve a remap destination, which may be relative to the submit dir."""
    path = _local_output_path(dest)
    if path is None:
        return None
    if path.is_absolute():
        return path.resolve()

    candidates = [Path.cwd() / path]
    if output_root is not None:
        candidates.append(output_root / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _collect_output_files(
    sub: JobSubmission, meta: dict, seen: set[Path]
) -> list[dict]:
    """List all files for one submission, including nested and remapped ones."""
    entries: list[dict] = []
    output_root = _output_root(sub)

    for proc_id, root in _scan_roots(sub):
        for path in _iter_files(root):
            resolved = path.resolve()
            if resolved in seen:
                continue
            entry = _output_file_entry(path, root, sub, meta, proc_id)
            if entry is not None:
                seen.add(resolved)
                entries.append(entry)

    for dest in _remap_destinations(sub):
        path = _resolve_remap(dest, output_root)
        if path is None:
            continue
        if path.is_file() and not path.is_symlink():
            if path in seen:
                continue
            entry = _output_file_entry(path, path.parent, sub, meta, 0)
            if entry is not None:
                seen.add(path)
                entries.append(entry)
        elif path.is_dir() and not path.is_symlink():
            for file_path in _iter_files(path):
                resolved = file_path.resolve()
                if resolved in seen:
                    continue
                entry = _output_file_entry(file_path, path, sub, meta, 0)
                if entry is not None:
                    seen.add(resolved)
                    entries.append(entry)

    return entries


def _allowed_output_file(
    sub: JobSubmission, filename: str, root_value: str | None
) -> Path:
    """Resolve a requested output file, rejecting roots we did not publish."""
    requested_root = (
        Path(root_value).expanduser().resolve() if root_value else _output_root(sub)
    )
    if requested_root is None:
        abort(404, description="Output destination not found")

    for _proc_id, allowed_root in _scan_roots(sub):
        if requested_root == allowed_root.resolve():
            return _safe_path(str(requested_root), filename)

    output_root = _output_root(sub)
    for dest in _remap_destinations(sub):
        target = _resolve_remap(dest, output_root)
        if target is None:
            continue
        if (
            target.is_dir()
            and not target.is_symlink()
            and requested_root == target.resolve()
        ):
            return _safe_path(str(requested_root), filename)
        if (
            target.is_file()
            and not target.is_symlink()
            and requested_root == target.parent.resolve()
            and _safe_path(str(requested_root), filename) == target.resolve()
        ):
            return target.resolve()

    abort(400, description="Invalid output root")


def _parse_requested_files(data: dict) -> dict[int, list[tuple[str, str | None]]]:
    """Group requested ``{cluster_id, filename, root}`` items by cluster."""
    by_cluster: dict[int, list[tuple[str, str | None]]] = {}
    for item in data["files"]:
        cid = item.get("cluster_id")
        fname = str(item.get("filename") or "")
        if cid is None or not fname:
            continue
        root = item.get("root")
        by_cluster.setdefault(int(cid), []).append((fname, str(root) if root else None))
    return by_cluster


@api_bp.route("/output-files")
def list_output_files():
    """List all output files from completed jobs.

    Uses ``output_destination`` and ``transfer_output_remaps`` stored in the
    JobSubmission record to locate output files.  Directories are scanned
    recursively so nested output and per-proc directories are included.

    Builds a cluster_id → {name, command} lookup in a single query
    to avoid N+1 queries when enriching each output file entry.
    """
    submissions = (
        JobSubmission.query.filter(
            or_(
                JobSubmission.output_destination.isnot(None),
                JobSubmission.transfer_output_remaps.isnot(None),
            )
        )
        .order_by(JobSubmission.submitted_at.desc())
        .all()
    )

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

    output_files: list[dict] = []
    seen: set[Path] = set()
    try:
        for sub in submissions:
            meta = cluster_meta.get(sub.cluster_id, {"name": sub.name, "command": ""})
            output_files.extend(_collect_output_files(sub, meta, seen))

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
    if not submission:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _allowed_output_file(submission, filename, request.args.get("root"))

    if not file_path.is_file():
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

    Request JSON: {"files": [{"cluster_id": 123, "filename": "a.png",
    "root": "/path/to/output"}, ...]}.  ``root`` is optional for legacy
    clients and required for remapped files outside the output directory.
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    by_cluster = _parse_requested_files(data)
    if not by_cluster:
        return jsonify({"error": "No valid files"}), 400

    subs = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(list(by_cluster.keys()))
    ).all()
    sub_by_cluster = {s.cluster_id: s for s in subs}

    skipped: list[str] = []
    entries: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    for cid, files in by_cluster.items():
        submission = sub_by_cluster.get(cid)
        for fname, root in files:
            if submission is None:
                skipped.append(f"{cid}/{fname}")
                continue
            try:
                file_path = _allowed_output_file(submission, fname, root)
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

    Request JSON: {"files": [{"cluster_id": 123, "filename": "a.png",
    "root": "/path/to/output"}, ...]}
    """
    data = request.get_json()
    if not data or not isinstance(data.get("files"), list) or not data["files"]:
        return jsonify({"error": "Missing 'files' list"}), 400

    by_cluster = _parse_requested_files(data)
    if not by_cluster:
        return jsonify({"error": "No valid files"}), 400

    subs = JobSubmission.query.filter(
        JobSubmission.cluster_id.in_(list(by_cluster.keys()))
    ).all()
    sub_by_cluster = {s.cluster_id: s for s in subs}

    deleted: list[str] = []
    failed: list[dict] = []
    try:
        for cid, files in by_cluster.items():
            submission = sub_by_cluster.get(cid)
            for fname, root in files:
                if submission is None:
                    failed.append(
                        {"filename": f"{cid}/{fname}", "error": "no output destination"}
                    )
                    continue
                try:
                    file_path = _allowed_output_file(submission, fname, root)
                except Exception:  # noqa: BLE001 — traversal → fail that file
                    failed.append(
                        {"filename": f"{cid}/{fname}", "error": "invalid path"}
                    )
                    continue
                if not file_path.is_file():
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
    """Download a specific output file for a given job."""
    submission = JobSubmission.query.filter_by(cluster_id=cluster_id).first()
    if not submission:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _allowed_output_file(submission, filename, request.args.get("root"))

    if not file_path.is_file():
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
    if not submission:
        return jsonify(
            {"error": f"Output destination not found for cluster {cluster_id}"}
        ), 404

    file_path = _allowed_output_file(submission, filename, request.args.get("root"))

    if not file_path.is_file():
        return jsonify({"error": f"Output file not found: {filename}"}), 404

    try:
        file_path.unlink()
        return jsonify({"message": f"Deleted output file: {filename}"})
    except Exception:
        logger.exception("Failed to delete output file")
        return jsonify({"error": "Failed to delete output file"}), 500
