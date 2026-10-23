"""Shared helpers for the API blueprint package."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from flask import Response, abort, send_file

from app.utils import (
    safe_join,
    scan_uuid_directories,
)

logger = logging.getLogger(__name__)


def build_zip_response(
    entries: list[tuple[str, Path]], *, download_name: str
) -> tuple[Response, list[str]] | None:
    """Bundle the given (arcname, path) pairs into an in-memory zip.

    Only files that exist on disk are archived; duplicate arcnames get a
    "name (2)" style suffix.  Returns ``(response, skipped)`` with the
    missing paths reported in ``skipped`` (and in an ``X-Skipped-Files``
    header), or ``None`` when nothing could be archived at all.
    """
    buffer = io.BytesIO()
    skipped: list[str] = []
    archived = 0
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in entries:
            if not path.exists() or not path.is_file():
                skipped.append(arcname)
                continue
            name = path.name
            if name in used:
                stem, suffix, i = path.stem, path.suffix, 2
                while name in used:
                    name = f"{stem} ({i}){suffix}"
                    i += 1
            used.add(name)
            zf.writestr(name, path.read_bytes())
            archived += 1

    if archived == 0:
        return None

    buffer.seek(0)
    response = send_file(
        buffer,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/zip",
    )
    if skipped:
        response.headers["X-Skipped-Files"] = ",".join(skipped[:20])
    logger.info(
        "Bulk download %s: %d file(s) archived, %d skipped",
        download_name,
        archived,
        len(skipped),
    )
    return response, skipped


def _safe_path(base_dir: str, *relative: str) -> Path:
    """Join user-supplied path parts under *base_dir* or abort with 400.

    Wraps :func:`app.utils.safe_join` so every file endpoint rejects
    path-traversal attempts uniformly (e.g., ``../..`` in the URL path,
    rename targets, or upload filenames).
    """
    try:
        return safe_join(base_dir, *relative)
    except ValueError:
        abort(400, description="Invalid path")


def _osdf_uri(base_uri: str, abs_path: str | Path) -> str:
    """Build an OSDF URI from a base URI and an absolute file path.

    Correctly handles bases with or without an authority component:
    ``osdf:///`` + ``/tmp/f`` → ``osdf:///tmp/f`` and
    ``osdf://host`` + ``/tmp/f`` → ``osdf://host/tmp/f``.
    """
    path = str(abs_path)
    if not path.startswith("/"):
        path = "/" + path
    if "://" in base_uri:
        scheme, _, rest = base_uri.partition("://")
        return f"{scheme}://{rest.rstrip('/')}{path}"
    return base_uri.rstrip("/") + path


def _resolve_path(path: str) -> str:
    """Resolve a path to an absolute, normalized string."""
    return str(Path(path).resolve())


def _remove_empty_parents(path: Path) -> None:
    """Remove empty ancestor directories, stopping at the first non-empty one."""
    for parent in [path, *path.parents]:
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            else:
                break
        except OSError, PermissionError:
            break


def _find_existing_file_by_original_name(
    base_dir: str, original_name: str
) -> dict | None:
    """Scan UUID-named subdirectories under *base_dir* for a file matching *original_name*.

    Returns the file entry dict (with keys ``filename``, ``original_name``, etc.)
    if found, or ``None``.
    """
    for entry in scan_uuid_directories(base_dir):
        if entry.get("original_name") == original_name:
            return entry
    return None


def container_display_name(filename: str) -> str:
    """Derive a human-readable display name from a ``.sif`` filename.

    E.g., ``ubuntu_latest.sif`` → ``Ubuntu Latest``.
    """
    return Path(filename).stem.replace("_", " ").title()


def _find_existing_container_by_name(containers_dir: str, name: str) -> dict | None:
    """Scan the containers directory for a container with the same display *name*.

    The display name is derived from the ``.sif`` filename stem (e.g.,
    ``ubuntu_latest.sif`` → ``Ubuntu Latest``).  Returns the container entry
    dict if found, or ``None``.
    """
    for entry in scan_uuid_directories(containers_dir, file_filter=".sif"):
        if container_display_name(entry["original_name"]).lower() == name.lower():
            return entry
    return None
