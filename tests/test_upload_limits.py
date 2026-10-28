"""Large streamed uploads use the larger upload limit."""

import time
from pathlib import Path


def test_slow_container_scan_returns_pending(secure_app, secure_client, monkeypatch):
    containers_dir = str(Path(secure_app.config["OSDF_ROOT_PATH"]) / "containers")
    from app.api import containers as containers_api

    real_scan = containers_api.scan_uuid_directories

    def slow_scan(path, **kwargs):
        if str(path) == containers_dir:
            time.sleep(1.0)
            return []
        return real_scan(path, **kwargs)

    monkeypatch.setattr(containers_api, "scan_uuid_directories", slow_scan)

    started = time.monotonic()
    first = secure_client.get("/api/containers").get_json()
    elapsed = time.monotonic() - started

    assert elapsed < 0.8, f"container request blocked for {elapsed:.2f}s"
    assert first["pending"] is True

    time.sleep(1.1)
    second = secure_client.get("/api/containers").get_json()
    assert second["pending"] is False


def test_streamed_upload_uses_larger_limit(secure_app, secure_client):
    secure_app.config["MAX_CONTENT_LENGTH"] = 16
    secure_app.config["MAX_UPLOAD_LENGTH"] = 1024

    resp = secure_client.post(
        "/api/files",
        data=b"x" * 64,
        headers={"X-Upload-Filename": "larger-than-json-limit.bin"},
    )

    assert resp.status_code == 201, resp.get_json()
