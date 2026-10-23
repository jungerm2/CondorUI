"""REST API blueprint package for HTCondor job management.

Route modules import ``api_bp`` from this package and register their routes
onto it, so endpoint names (``api.<fn>``) and the ``/api`` prefix are unchanged
from the pre-split single-module layout.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Re-exported so tests can monkeypatch one point (``app.api.daemon_available``);
# route modules resolve it through this package at call time.
from app.condor import daemon_available  # noqa: F401


@api_bp.errorhandler(Exception)
def handle_error(e: Exception):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    logger.exception("Unhandled API error")
    # Don't leak internal details (paths, stack info) to clients
    return jsonify({"error": "Internal server error"}), 500


@api_bp.route("/health")
def health_check():
    """Lightweight health check — does not query the schedd."""
    return jsonify({"status": "ok"})


# Route modules register their endpoints on api_bp at import time.
from app.api import (  # noqa: F401  # api_bp must exist before route modules
    containers,
    executables,
    files,
    history,
    jobs,
    output_files,
    quotas,
    submit,
    templates,
)
