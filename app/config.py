"""Application configuration."""

import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    """Default configuration for the Condor Web UI."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "condor-webui-dev-key")

    # SQLite database in the instance folder
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'condor_webui.db')}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Directory for uploaded submit files and input files
    UPLOAD_DIR = os.environ.get(
        "UPLOAD_DIR", os.path.join(BASE_DIR, "uploads")
    )

    # OSDF staging path for file transfers — uploaded files are copied here
    # so HTCondor can cache them via OSDF.
    OSDF_STAGING_PATH = os.environ.get(
        "OSDF_STAGING_PATH", ""
    )

    # Maximum number of history results to return by default
    MAX_HISTORY_RESULTS = int(os.environ.get("MAX_HISTORY_RESULTS", "200"))

    # Maximum upload size (50 MB)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
