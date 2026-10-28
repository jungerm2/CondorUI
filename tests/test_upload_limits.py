"""Large streamed uploads use the larger upload limit."""


def test_streamed_upload_uses_larger_limit(secure_app, secure_client):
    secure_app.config["MAX_CONTENT_LENGTH"] = 16
    secure_app.config["MAX_UPLOAD_LENGTH"] = 1024

    resp = secure_client.post(
        "/api/files",
        data=b"x" * 64,
        headers={"X-Upload-Filename": "larger-than-json-limit.bin"},
    )

    assert resp.status_code == 201, resp.get_json()
