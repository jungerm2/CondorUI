"""Large streamed uploads and legacy loose-file layouts."""

from pathlib import Path


def test_flat_input_file_is_listed(secure_app, secure_client):
    upload_dir = Path(secure_app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "loose.txt").write_text("loose")

    resp = secure_client.get("/api/files")

    assert resp.status_code == 200
    assert [f["original_name"] for f in resp.get_json()["files"]] == ["loose.txt"]


def test_flat_container_is_listed(secure_app, secure_client):
    container_dir = Path(secure_app.config["OSDF_ROOT_PATH"]) / "containers"
    container_dir.mkdir(parents=True)
    (container_dir / "loose.sif").write_bytes(b"sif")

    resp = secure_client.get("/api/containers")

    assert resp.status_code == 200
    assert [c["name"] for c in resp.get_json()["containers"]] == ["Loose"]


def test_streamed_upload_uses_larger_limit(secure_app, secure_client):
    secure_app.config["MAX_CONTENT_LENGTH"] = 16
    secure_app.config["MAX_UPLOAD_LENGTH"] = 1024

    resp = secure_client.post(
        "/api/files",
        data=b"x" * 64,
        headers={"X-Upload-Filename": "larger-than-json-limit.bin"},
    )

    assert resp.status_code == 201, resp.get_json()
