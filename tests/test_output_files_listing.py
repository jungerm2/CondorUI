"""Output-file discovery: nested trees, remaps, OSDF paths, and procs."""

import json
from pathlib import Path

from app import db
from app.models import JobSubmission


def _add_submission(app, **kwargs):
    with app.app_context():
        db.session.add(
            JobSubmission(
                submit_description=json.dumps({"executable": "/bin/true"}),
                **{"name": "Test job", "num_procs": 1, **kwargs},
            )
        )
        db.session.commit()


def _listing(client):
    resp = client.get("/api/output-files")
    assert resp.status_code == 200, resp.get_json()
    return {entry["filename"]: entry for entry in resp.get_json()["output_files"]}


def test_lists_nested_files_with_relative_paths(secure_app, secure_client):
    out_dir = secure_app.extensions["test_dirs"]["output_dir"] / "123"
    (out_dir / "frames" / "sub").mkdir(parents=True)
    (out_dir / "notes.txt").write_text("notes")
    (out_dir / "frames" / "sub" / "0001.png").write_bytes(b"png")
    _add_submission(secure_app, cluster_id=123, output_destination=str(out_dir))

    files = _listing(secure_client)
    assert set(files) == {"notes.txt", "frames/sub/0001.png"}
    nested = files["frames/sub/0001.png"]
    assert nested["root"] == str(out_dir.resolve())
    assert nested["path"] == str((out_dir / "frames" / "sub" / "0001.png").resolve())

    resp = secure_client.get("/api/output-files/download/123/frames/sub/0001.png")
    assert resp.status_code == 200
    assert resp.data == b"png"


def test_remap_only_submission_is_listed_and_downloadable(secure_app, secure_client):
    remap_dir = secure_app.extensions["test_dirs"]["tmp_path"] / "remapped"
    remap_dir.mkdir()
    dest = remap_dir / "result.txt"
    dest.write_text("remapped output")
    _add_submission(
        secure_app,
        cluster_id=124,
        output_destination=None,
        transfer_output_remaps=f"result.txt = {dest}",
    )

    files = _listing(secure_client)
    assert files["result.txt"]["root"] == str(remap_dir.resolve())

    resp = secure_client.get(
        "/api/output-files/download/124/result.txt",
        query_string={"root": str(remap_dir)},
    )
    assert resp.status_code == 200
    assert resp.data == b"remapped output"

    # Without a root the remap-only submission still has no base directory.
    assert (
        secure_client.get("/api/output-files/download/124/result.txt").status_code
        == 404
    )


def test_unpublished_root_is_rejected(secure_app, secure_client):
    remap_dir = secure_app.extensions["test_dirs"]["tmp_path"] / "remapped"
    remap_dir.mkdir()
    (remap_dir / "result.txt").write_text("ok")
    _add_submission(
        secure_app,
        cluster_id=125,
        transfer_output_remaps=f"result.txt = {remap_dir / 'result.txt'}",
    )

    secret_dir = secure_app.extensions["test_dirs"]["tmp_path"] / "secret"
    secret_dir.mkdir()
    (secret_dir / "secret.txt").write_text("do not serve")

    resp = secure_client.get(
        "/api/output-files/download/125/secret.txt",
        query_string={"root": str(secret_dir)},
    )
    assert resp.status_code == 400


def test_osdf_output_directory_maps_to_local_root(secure_app, secure_client):
    out_dir = secure_app.extensions["test_dirs"]["osdf_root"] / "outputs" / "126"
    out_dir.mkdir(parents=True)
    (out_dir / "frame.png").write_bytes(b"frame")
    _add_submission(
        secure_app,
        cluster_id=126,
        output_destination=f"osdf:///chtc{out_dir}",
    )

    files = _listing(secure_client)
    assert files["frame.png"]["root"] == str(out_dir.resolve())
    resp = secure_client.get("/api/output-files/download/126/frame.png")
    assert resp.status_code == 200
    assert resp.data == b"frame"


def test_per_proc_output_directories_are_included(secure_app, secure_client):
    cluster_dir = secure_app.extensions["test_dirs"]["output_dir"] / "127"
    for proc_id in range(3):
        proc_dir = cluster_dir / str(proc_id)
        proc_dir.mkdir(parents=True)
        (proc_dir / "result.txt").write_text(f"proc {proc_id}")
    _add_submission(
        secure_app,
        cluster_id=127,
        num_procs=3,
        output_destination=str(cluster_dir / "0"),
    )

    files = secure_client.get("/api/output-files").get_json()["output_files"]
    assert {entry["proc_id"] for entry in files} == {0, 1, 2}
    assert {Path(entry["root"]).name for entry in files} == {"0", "1", "2"}

    resp = secure_client.get(
        "/api/output-files/download/127/result.txt",
        query_string={"root": str(cluster_dir / "2")},
    )
    assert resp.status_code == 200
    assert resp.data == b"proc 2"


def test_shared_output_root_is_not_listed_twice(secure_app, secure_client):
    out_dir = secure_app.extensions["test_dirs"]["output_dir"] / "128"
    out_dir.mkdir(parents=True)
    (out_dir / "shared.txt").write_text("shared")
    _add_submission(secure_app, cluster_id=128, output_destination=str(out_dir))
    _add_submission(secure_app, cluster_id=129, output_destination=str(out_dir))

    files = secure_client.get("/api/output-files").get_json()["output_files"]
    assert len(files) == 1
    assert files[0]["filename"] == "shared.txt"


def test_bulk_actions_accept_remapped_root(secure_app, secure_client):
    remap_dir = secure_app.extensions["test_dirs"]["tmp_path"] / "bulk-remap"
    remap_dir.mkdir()
    dest = remap_dir / "result.txt"
    dest.write_text("bulk output")
    _add_submission(
        secure_app,
        cluster_id=130,
        transfer_output_remaps=f"result.txt = {dest}",
    )
    files = [{"cluster_id": 130, "filename": "result.txt", "root": str(remap_dir)}]

    resp = secure_client.post("/api/output-files/bulk-download", json={"files": files})
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"

    resp = secure_client.delete("/api/output-files/delete-bulk", json={"files": files})
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == ["130/result.txt"]
    assert not dest.exists()


def test_scans_output_dir_without_any_submission(secure_app, secure_client):
    out_dir = secure_app.extensions["test_dirs"]["output_dir"] / "00000200"
    (out_dir / "nested").mkdir(parents=True)
    (out_dir / "nested" / "frame.png").write_bytes(b"frame")
    (out_dir / "notes.txt").write_text("notes")

    files = _listing(secure_client)
    assert set(files) == {"nested/frame.png", "notes.txt"}
    assert files["nested/frame.png"]["cluster_id"] == 200
    assert files["nested/frame.png"]["root"] == str(out_dir.resolve())

    resp = secure_client.get(
        "/api/output-files/download/200/nested/frame.png",
        query_string={"root": str(out_dir)},
    )
    assert resp.status_code == 200
    assert resp.data == b"frame"


def test_disk_scan_uses_submission_metadata_when_path_is_missing(
    secure_app, secure_client
):
    out_dir = secure_app.extensions["test_dirs"]["output_dir"] / "201"
    out_dir.mkdir(parents=True)
    (out_dir / "result.txt").write_text("result")
    _add_submission(
        secure_app,
        cluster_id=201,
        name="Disk-only job",
        output_destination=None,
    )

    files = _listing(secure_client)
    assert files["result.txt"]["job_name"] == "Disk-only job"
    assert files["result.txt"]["cluster_id"] == 201


def test_files_directly_under_output_dir_are_listed(secure_app, secure_client):
    output_dir = secure_app.extensions["test_dirs"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "loose.txt").write_text("loose")

    files = _listing(secure_client)
    entry = files["loose.txt"]
    assert entry["cluster_id"] == 0
    assert entry["job_name"] == "Other outputs"
    assert entry["root"] == str(output_dir.resolve())

    resp = secure_client.delete(
        "/api/output-files/delete-bulk",
        json={
            "files": [
                {"cluster_id": 0, "filename": "loose.txt", "root": str(output_dir)}
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == ["0/loose.txt"]
    assert not (output_dir / "loose.txt").exists()
