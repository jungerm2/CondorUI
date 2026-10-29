"""Folder uploads preserve relative paths and remain normal file entries."""

from pathlib import Path
from urllib.parse import quote

BATCH = "a" * 32


def _upload(client, relative, data=b"data", batch=BATCH):
    return client.post(
        "/api/files",
        data=data,
        headers={
            "X-Upload-Filename": Path(relative).name,
            "X-Upload-Batch": batch,
            "X-Upload-Relative-Path": quote(relative),
        },
    )


def _url_path(filename):
    return "/".join(quote(part) for part in filename.split("/"))


def test_folder_upload_preserves_nested_path(secure_app, secure_client):
    relative = "dataset/frames/0001.txt"
    resp = _upload(secure_client, relative)

    assert resp.status_code == 201, resp.get_json()
    uploaded = resp.get_json()
    expected = f"{BATCH}/{relative}"
    assert uploaded["filename"] == expected
    assert uploaded["original_name"] == "0001.txt"
    assert uploaded["display_name"] == relative
    assert Path(uploaded["local_path"]).is_file()

    files = secure_client.get("/api/files").get_json()["files"]
    entry = next(f for f in files if f["filename"] == expected)
    assert entry["display_name"] == relative
    assert entry["original_name"] == "0001.txt"

    download = secure_client.get(f"/api/files/{_url_path(expected)}/download")
    assert download.status_code == 200
    assert download.data == b"data"


def test_folder_upload_rejects_traversal(secure_app, secure_client):
    outside = Path(secure_app.extensions["test_dirs"]["tmp_path"]) / "outside.txt"

    resp = _upload(secure_client, "../outside.txt")

    assert resp.status_code == 400
    assert not outside.exists()


def test_nested_file_can_be_renamed(secure_app, secure_client):
    relative = "dataset/frames/0001.txt"
    expected = f"{BATCH}/{relative}"
    assert _upload(secure_client, relative).status_code == 201

    resp = secure_client.put(
        f"/api/files/{_url_path(expected)}", json={"filename": "renamed.txt"}
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["filename"] == f"{BATCH}/dataset/frames/renamed.txt"
    assert (
        Path(secure_app.config["UPLOAD_DIR"])
        / BATCH
        / "dataset"
        / "frames"
        / "renamed.txt"
    ).is_file()
