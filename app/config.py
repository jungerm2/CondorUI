"""Application configuration."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Default configuration for the Condor Web UI."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "condor-webui-dev-key")

    # SQLite database in the instance folder
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'instance' / 'condor_webui.db'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Directory for uploaded submit files and input files
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(BASE_DIR / "uploads"))

    # Directory for job stdout, stderr, and user logs (outside project root)
    JOB_LOGS_DIR = os.environ.get(
        "JOB_LOGS_DIR", str(BASE_DIR.parent / "condor_job_logs")
    )

    # OSDF root path for file transfers — uploaded files and containers are
    # stored in subdirectories under this path so HTCondor can cache them via OSDF.
    OSDF_ROOT_PATH = os.environ.get("OSDF_ROOT_PATH", "")

    # Base URI prefix for OSDF-staged files (e.g., "osdf:///" or "gsiftp://...")
    OSDF_BASE_URI = os.environ.get("OSDF_BASE_URI", "osdf:///")

    # Directory for output files transferred back from completed jobs.
    # Each job gets a per-cluster subfolder: OUTPUT_DIR/<ClusterId>/
    OUTPUT_DIR = os.environ.get("OUTPUT_DIR", str(BASE_DIR / "outputs"))

    # Maximum number of history results to return by default
    MAX_HISTORY_RESULTS = int(os.environ.get("MAX_HISTORY_RESULTS", "200"))

    # Directory for uploaded executables (flat, no UUID paths)
    EXECUTABLES_DIR = os.environ.get("EXECUTABLES_DIR", str(BASE_DIR / "executables"))

    # Directory for submit templates (stored as .sub files)
    TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", str(BASE_DIR / "templates"))

    # Maximum upload size (10 GB) — containers can be very large
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024 * 1024
