"""Disk quota endpoint."""

from __future__ import annotations

import logging
import subprocess

from flask import jsonify

from app.api import api_bp

logger = logging.getLogger(__name__)


@api_bp.route("/quotas")
def get_quotas():
    """Get disk quota information from the `get_quotas` command."""
    try:
        result = subprocess.run(  # noqa: PLW1510
            ["get_quotas"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return jsonify(
                {"error": f"get_quotas failed: {result.stderr.strip()}"}
            ), 500

        # Parse the tabular output
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return jsonify({"quotas": []})

        headers_raw = lines[0].split()
        # Map header names to canonical keys
        header_map = {
            "Path": "path",
            "Disk_Used(GB)": "disk_used_gb",
            "Disk_Limit(GB)": "disk_limit_gb",
            "Files_Used": "files_used",
            "File_Limit": "file_limit",
        }
        headers = []
        for h in headers_raw:
            headers.append(header_map.get(h, h.lower().replace(" ", "_")))

        quotas = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < len(headers):
                continue
            entry = {}
            for i, h in enumerate(headers):
                val = parts[i]
                if h in {"disk_used_gb", "disk_limit_gb", "files_used", "file_limit"}:
                    try:
                        entry[h] = float(val) if "." in val else int(val)
                    except ValueError:
                        # e.g. the "N/A" the quota tool prints when there is no limit
                        entry[h] = None
                else:
                    entry[h] = val
            quotas.append(entry)

        return jsonify({"quotas": quotas})
    except FileNotFoundError:
        return jsonify({"error": "get_quotas command not found on this system"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "get_quotas timed out"}), 500
    except Exception:
        logger.exception("Failed to fetch quotas")
        return jsonify({"error": "Failed to fetch quotas"}), 500
