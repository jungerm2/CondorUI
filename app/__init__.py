"""HTCondor Web UI — Flask application factory."""

import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app(config_override: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load default configuration
    app.config.from_object("app.config.Config")

    # Apply any overrides (e.g., for testing)
    if config_override:
        app.config.update(config_override)

    # Ensure instance and upload directories exist
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    os.makedirs(app.config["JOB_LOGS_DIR"], exist_ok=True)

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

    return app
