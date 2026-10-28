"""HTCondor Web UI — Flask application factory."""

import os
import threading

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA journal_size_limit=67108864")  # 64mb
    cursor.execute("PRAGMA mmap_size=134217728")  # 128mb
    cursor.execute("PRAGMA cache_size=2000")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def create_app(config_override: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load default configuration
    app.config.from_object("app.config.Config")

    # Apply any overrides (e.g., for testing)
    if config_override:
        app.config.update(config_override)

    # Ensure instance and data directories exist
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    os.makedirs(app.config["JOB_LOGS_DIR"], exist_ok=True)
    os.makedirs(app.config["TEMPLATES_DIR"], exist_ok=True)

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    from app.api import api_bp
    from app.views import views_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    # Create database tables
    with app.app_context():
        from app import models  # noqa: F401

        db.create_all()

    # Warm the slow staging listings without delaying startup.
    if not app.config.get("TESTING"):
        from app.api.containers import prewarm_container_listing
        from app.api.files import prewarm_staged_listing

        def _prewarm_staging() -> None:
            prewarm_staged_listing(app)
            prewarm_container_listing(app)

        threading.Thread(target=_prewarm_staging, daemon=True).start()

    return app
