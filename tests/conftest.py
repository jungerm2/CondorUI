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
                "TEMPLATES_DIR": str(Path(tmpdir) / "templates"),
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


@pytest.fixture()
def secure_app(tmp_path):
    """App with per-test isolated directories, for path-safety tests.

    Exposes the directories via ``app.extensions["test_dirs"]`` so tests can
    plant marker files outside the base dirs and assert they were untouched.
    """
    dirs = {
        "upload_dir": tmp_path / "uploads",
        "osdf_root": tmp_path / "osdf",
        "output_dir": tmp_path / "outputs",
        "logs_dir": tmp_path / "logs",
        "templates_dir": tmp_path / "templates",
    }
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "UPLOAD_DIR": str(dirs["upload_dir"]),
            "OSDF_ROOT_PATH": str(dirs["osdf_root"]),
            "OUTPUT_DIR": str(dirs["output_dir"]),
            "JOB_LOGS_DIR": str(dirs["logs_dir"]),
            "TEMPLATES_DIR": str(dirs["templates_dir"]),
            "EXECUTABLES_DIR": str(tmp_path / "executables"),
            "SERVER_NAME": "localhost",
        }
    )
    with app.app_context():
        _db.create_all()

    app.extensions["test_dirs"] = {"tmp_path": tmp_path, **dirs}
    return app


@pytest.fixture()
def secure_client(secure_app):
    return secure_app.test_client()
