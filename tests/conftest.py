"""Pytest fixtures for Condor Web UI tests."""

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import create_app
from app import db as _db


@pytest.fixture(scope="session")
def app():
    """Create a Flask app instance for testing with an in-memory database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "UPLOAD_DIR": str(Path(tmpdir) / "uploads"),
                "JOB_LOGS_DIR": str(Path(tmpdir) / "logs"),
                "OUTPUT_DIR": str(Path(tmpdir) / "outputs"),
                "WTF_CSRF_ENABLED": False,
                "SERVER_NAME": "localhost",
            }
        )

        with app.app_context():
            _db.create_all()

        yield app


@pytest.fixture(scope="session")
def client(app):
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def db(app):
    """Provide a clean database for each test function."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Override browser context args for testing."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def live_server(app):
    """Run the Flask app in a background thread for Playwright to connect to."""
    # Find a random available port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Give the server a moment to start
    time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    thread.join(timeout=2)
