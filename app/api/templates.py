"""Submit-template endpoints."""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import UTC
from pathlib import Path

from flask import current_app, jsonify, request, send_file

from app.api import api_bp

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Convert a template name to a safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "untitled"


def _template_path(templates_dir: str, name: str) -> Path:
    """Get the filesystem path for a template by name."""
    return Path(templates_dir) / f"{_slugify(name)}.json"


def _read_template(file_path: Path) -> dict | None:
    """Read a template from a .json file and return its metadata dict."""
    if not file_path.exists():
        return None
    try:
        content = file_path.read_text(encoding="utf-8")
        stat = file_path.stat()
        # Derive the display name from the filename (slug → Title Case)
        name = file_path.stem.replace("-", " ").title()
        return {
            "name": name,
            "submit_data": content,
            "updated_at": stat.st_mtime,
        }
    except Exception:  # noqa: BLE001
        return None


def _template_to_dict(file_path: Path) -> dict | None:
    """Convert a .json file to the API response dict."""
    tmpl = _read_template(file_path)
    if tmpl is None:
        return None
    from datetime import datetime

    return {
        "name": tmpl["name"],
        "submit_data": tmpl["submit_data"],
        "updated_at": datetime.fromtimestamp(tmpl["updated_at"], tz=UTC).isoformat(),
    }


@api_bp.route("/templates")
def list_templates():
    """List all saved submit templates (from .json files on disk)."""
    templates_dir = current_app.config["TEMPLATES_DIR"]
    templates = []
    for f in sorted(
        Path(templates_dir).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        if f.suffix == ".json":
            d = _template_to_dict(f)
            if d:
                templates.append(d)
    return jsonify({"templates": templates})


@api_bp.route("/templates", methods=["POST"])
def create_template():
    """Save a new submit template as a .json file."""
    data = request.get_json()
    if not data or "name" not in data or "submit_data" not in data:
        return jsonify({"error": "Missing 'name' or 'submit_data'"}), 400

    templates_dir = current_app.config["TEMPLATES_DIR"]
    file_path = _template_path(templates_dir, data["name"])

    if file_path.exists():
        return jsonify({"error": f"Template '{data['name']}' already exists"}), 409

    # Store submit_data as-is (raw text for raw mode, JSON string for form mode)
    content = (
        json.dumps(data["submit_data"], indent=2)
        if isinstance(data["submit_data"], dict)
        else data["submit_data"]
    )
    file_path.write_text(content, encoding="utf-8")

    return jsonify(_template_to_dict(file_path)), 201


@api_bp.route("/templates/<name>", methods=["PUT"])
def update_template(name: str):
    """Update an existing template (.json file)."""
    templates_dir = current_app.config["TEMPLATES_DIR"]
    file_path = _template_path(templates_dir, name)

    if not file_path.exists():
        return jsonify({"error": f"Template '{name}' not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400

    # If name changed, rename the file
    if "name" in data and data["name"] != name:
        new_path = _template_path(templates_dir, data["name"])
        if new_path.exists():
            return jsonify({"error": f"Template '{data['name']}' already exists"}), 409
        file_path.rename(new_path)
        file_path = new_path

    # If submit_data changed, rewrite the file
    if "submit_data" in data:
        content = (
            json.dumps(data["submit_data"], indent=2)
            if isinstance(data["submit_data"], dict)
            else data["submit_data"]
        )
        file_path.write_text(content, encoding="utf-8")

    return jsonify(_template_to_dict(file_path))


@api_bp.route("/templates/<name>", methods=["DELETE"])
def delete_template(name: str):
    """Delete a template (.json file)."""
    templates_dir = current_app.config["TEMPLATES_DIR"]
    file_path = _template_path(templates_dir, name)

    if not file_path.exists():
        return jsonify({"error": f"Template '{name}' not found"}), 404

    file_path.unlink()
    return jsonify({"message": f"Template '{name}' deleted"})


def _template_to_sub(submit_data: str) -> str:
    """Convert a template's stored submit_data into standard .sub file syntax.

    If submit_data is a JSON string representing an object (form mode), it is
    converted to standard .sub syntax.  If it is already raw .sub text, it is
    returned as-is.
    """
    content = submit_data or ""
    try:
        if content.strip().startswith("{"):
            parsed = json.loads(content)
            lines = []
            key_order = [
                "universe",
                "container_image",
                "executable",
                "shell",
                "arguments",
                "transfer_input_files",
                "transfer_executable",
                "request_cpus",
                "request_memory",
                "request_disk",
                "request_gpus",
                "gpus_minimum_capability",
                "gpus_minimum_memory",
                "gpus_minimum_runtime",
                "cuda_version",
                "output",
                "error",
                "log",
                "transfer_output_files",
                "output_directory",
                "transfer_output_remaps",
            ]
            # Standard keys in order
            for key in key_order:
                val = parsed.get(key)
                if val is not None and val != "" and val != 0 and val is not False:
                    lines.append(f"{key} = {val}")
            # Extra keys (not in standard list)
            standard_set = set(key_order) | {"queue"}
            for key, val in parsed.items():
                if key not in standard_set and val is not None and val != "":
                    lines.append(f"{key} = {val}")
            # Queue directive
            queue_val = parsed.get("queue", 1)
            lines.append(f"\nqueue {queue_val}")
            content = "\n".join(lines)
    except json.JSONDecodeError, TypeError:
        # If parsing fails, use raw content as-is
        pass
    return content


@api_bp.route("/templates/<name>/download")
def download_template(name: str):
    """Download a template as a .sub file."""
    templates_dir = current_app.config["TEMPLATES_DIR"]
    file_path = _template_path(templates_dir, name)

    tmpl = _read_template(file_path)
    if tmpl is None:
        return jsonify({"error": f"Template '{name}' not found"}), 404

    content = _template_to_sub(tmpl.get("submit_data", ""))

    # Sanitize filename for .sub download
    safe_name = _slugify(name)
    download_name = f"{safe_name}.sub"

    return send_file(
        io.BytesIO(content.encode("utf-8")),
        as_attachment=True,
        download_name=download_name,
        mimetype="text/plain",
    )


@api_bp.route("/templates/<name>/preview")
def preview_template(name: str):
    """Return the .sub representation of a template as JSON for client-side preview."""
    templates_dir = current_app.config["TEMPLATES_DIR"]
    file_path = _template_path(templates_dir, name)

    tmpl = _read_template(file_path)
    if tmpl is None:
        return jsonify({"error": f"Template '{name}' not found"}), 404

    content = _template_to_sub(tmpl.get("submit_data", ""))
    return jsonify({"name": tmpl["name"], "content": content})
