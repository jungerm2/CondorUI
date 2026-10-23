"""Security regression tests: path traversal in file-management endpoints.

Every endpoint that accepts a user-supplied filename (URL path, rename
target, or upload header) must reject — or sanitize — attempts to escape
its base directory.  These tests create an app with isolated temp
directories and attempt a battery of traversal payloads, asserting both
the HTTP status (400, never 500) and that no file *outside* the base
directory was touched.
"""

from pathlib import Path

import pytest

from app import db as _db
from app.models import JobSubmission


def _make_upload(client, name="file.txt", content=b"data"):
    """Upload a file via the raw-stream endpoint and return its uuid/name."""
    resp = client.post(
        "/api/files",
        data=content,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Upload-Filename": name,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["filename"]


class TestUploadFilenameSanitization:
    def test_upload_header_traversal_is_sanitized(self, secure_app, secure_client):
        """A traversal payload in X-Upload-Filename must not escape UPLOAD_DIR."""
        outside = secure_app.extensions["test_dirs"]["tmp_path"] / "evil.txt"
        resp = secure_client.post(
            "/api/files",
            data=b"data",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Filename": "../../evil.txt",
            },
        )
        assert resp.status_code == 201
        upload_dir = secure_app.extensions["test_dirs"]["upload_dir"]
        stored = Path(resp.get_json()["local_path"])
        assert stored.is_relative_to(upload_dir.resolve())
        assert stored.name == "evil.txt"
        assert not outside.exists()

    def test_upload_header_dotdot_only_rejected(self, secure_client):
        resp = secure_client.post(
            "/api/files",
            data=b"data",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Filename": "../..",
            },
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()


class TestFileEndpointTraversal:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("DELETE", "/api/files/../../outside.txt"),
            ("DELETE", "/api/files/uuid/../../outside.txt"),
            ("POST", "/api/files/../../outside.txt/stage"),
            ("POST", "/api/files/uuid/../../outside.txt/unstage"),
            ("PUT", "/api/files/../../outside.txt"),
        ],
    )
    def test_traversal_url_rejected(self, secure_app, secure_client, method, path):
        outside = secure_app.extensions["test_dirs"]["tmp_path"] / "outside.txt"
        outside.write_bytes(b"do-not-delete")

        kwargs = {}
        if method == "PUT":
            kwargs["json"] = {"filename": "renamed.txt"}

        resp = secure_client.open(path, method=method, **kwargs)
        # 400 = caught by safe_join; 404 = Werkzeug normalized the path
        # before routing.  Either way the request was rejected.
        assert resp.status_code in (400, 404), f"{method} {path} -> {resp.status_code}"
        assert outside.exists(), "file outside base dir was modified!"

    def test_rename_target_traversal_is_sanitized(self, secure_app, secure_client):
        """Renaming to '../evil.txt' must not write outside the UUID dir."""
        rel_name = _make_upload(secure_client, "file.txt")
        upload_dir = secure_app.extensions["test_dirs"]["upload_dir"]
        outside_marker = secure_app.extensions["test_dirs"]["tmp_path"] / "marker.txt"
        outside_marker.write_bytes(b"marker")

        resp = secure_client.put(
            f"/api/files/{rel_name}",
            json={"filename": "../evil.txt"},
        )
        assert resp.status_code == 200
        new_path = Path(resp.get_json()["local_path"])
        assert new_path.parent == (upload_dir / rel_name.split("/")[0]).resolve()
        assert new_path.name == "evil.txt"
        assert outside_marker.read_bytes() == b"marker"

    def test_delete_of_osdf_only_file_succeeds(self, secure_app, secure_client):
        """Deleting a file that exists only in OSDF must return 200, not 404."""
        osdf_uploads = secure_app.extensions["test_dirs"]["osdf_root"] / "uploads"
        staged = osdf_uploads / "u1" / "staged.txt"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"staged")

        resp = secure_client.delete("/api/files/u1/staged.txt")
        assert resp.status_code == 200
        assert not staged.exists()

    def test_delete_traversal_via_osdf_rejected(self, secure_app, secure_client):
        outside = secure_app.extensions["test_dirs"]["tmp_path"] / "outside.txt"
        outside.write_bytes(b"do-not-delete")
        resp = secure_client.delete("/api/files/u1/../../outside.txt")
        assert resp.status_code == 400
        assert outside.exists()


class TestContainerEndpointTraversal:
    def test_delete_container_traversal_rejected(self, secure_app, secure_client):
        outside = secure_app.extensions["test_dirs"]["tmp_path"] / "outside.sif"
        outside.write_bytes(b"sif")
        resp = secure_client.delete("/api/containers/../../outside.sif")
        assert resp.status_code == 400
        assert outside.exists()


class TestOutputFileEndpointTraversal:
    @pytest.fixture()
    def _submission(self, secure_app):
        with secure_app.app_context():
            sub = JobSubmission(
                cluster_id=123,
                name="test-job",
                submit_description="{}",
                output_destination=str(
                    secure_app.extensions["test_dirs"]["output_dir"] / "123"
                ),
            )
            _db.session.add(sub)
            _db.session.commit()

    def test_download_traversal_rejected(self, secure_app, secure_client, _submission):
        secret = secure_app.extensions["test_dirs"]["tmp_path"] / "secret.txt"
        secret.write_bytes(b"secret")
        resp = secure_client.get("/api/output-files/download/123/../../secret.txt")
        assert resp.status_code == 400
        assert secret.exists()

    def test_delete_traversal_rejected(self, secure_app, secure_client, _submission):
        secret = secure_app.extensions["test_dirs"]["tmp_path"] / "secret.txt"
        secret.write_bytes(b"secret")
        resp = secure_client.delete("/api/output-files/delete/123/../../secret.txt")
        assert resp.status_code == 400
        assert secret.exists()


class TestErrorHandling:
    def test_unhandled_exception_returns_generic_message(self, secure_app, monkeypatch):
        """The API error handler must not leak exception details."""
        monkeypatch.setattr(
            "app.api.files.scan_uuid_directories",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom: /internal/path")),
        )
        client = secure_app.test_client()
        resp = client.get("/api/files")
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "Internal server error"
        assert "/internal/path" not in resp.get_data(as_text=True)
