"""Input-file listing should not probe the OSDF mount once per local file."""

import time
from pathlib import Path


def test_local_listing_does_not_probe_osdf_per_file(
    secure_app, secure_client, monkeypatch
):
    upload_dir = Path(secure_app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    local_dir = upload_dir / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    local_dir.mkdir()
    (local_dir / "local.txt").write_text("local")

    osdf_uploads = Path(secure_app.config["OSDF_ROOT_PATH"]) / "uploads"
    osdf_uploads.mkdir(parents=True, exist_ok=True)

    original_exists = Path.exists
    osdf_probes: list[Path] = []

    def tracking_exists(self):
        path = Path(self)
        if path.is_relative_to(osdf_uploads):
            osdf_probes.append(path)
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", tracking_exists)

    resp = secure_client.get("/api/files")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["files"][0]["original_name"] == "local.txt"
    assert data["files"][0]["osdf_path"] is None
    # One probe for the OSDF uploads root; none for the local filename.
    assert osdf_probes == [osdf_uploads]


def test_slow_osdf_scan_does_not_block_local_files(
    secure_app, secure_client, monkeypatch
):
    upload_dir = Path(secure_app.config["UPLOAD_DIR"])
    local_dir = upload_dir / ("c" * 32)
    local_dir.mkdir(parents=True)
    (local_dir / "local.txt").write_text("local")
    osdf_uploads = str(Path(secure_app.config["OSDF_ROOT_PATH"]) / "uploads")

    from app.api import files as files_api

    real_scan = files_api.scan_uuid_directories

    def slow_scan(path, **kwargs):
        if str(path) == osdf_uploads:
            time.sleep(1.0)
            return []
        return real_scan(path, **kwargs)

    monkeypatch.setattr(files_api, "scan_uuid_directories", slow_scan)

    started = time.monotonic()
    first = secure_client.get("/api/files").get_json()
    elapsed = time.monotonic() - started

    assert elapsed < 0.8, f"local listing blocked for {elapsed:.2f}s"
    assert first["count"] == 1
    assert first["files"][0]["original_name"] == "local.txt"
    assert first["staged_pending"] is True

    time.sleep(1.1)
    second = secure_client.get("/api/files").get_json()
    assert second["count"] == 1
    assert second["staged_pending"] is False


def test_osdf_copy_still_wins_over_local(secure_app, secure_client):
    local_dir = Path(secure_app.config["UPLOAD_DIR"]) / ("b" * 32)
    local_dir.mkdir(parents=True)
    (local_dir / "same.txt").write_text("local")
    osdf_dir = Path(secure_app.config["OSDF_ROOT_PATH"]) / "uploads" / ("b" * 32)
    osdf_dir.mkdir(parents=True)
    (osdf_dir / "same.txt").write_text("staged")

    files = secure_client.get("/api/files").get_json()["files"]

    assert len(files) == 1
    assert files[0]["osdf_path"] is not None
    assert files[0]["local_path"] is None
