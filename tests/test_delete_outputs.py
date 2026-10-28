"""Deleting a job can also remove the output files it owns."""

import json
from pathlib import Path

from app import db
from app.models import JobSubmission


def _add_submission(app, cluster_id, **kwargs):
    with app.app_context():
        db.session.add(
            JobSubmission(
                cluster_id=cluster_id,
                name="Delete me",
                submit_description=json.dumps({"executable": "/bin/true"}),
                num_procs=kwargs.pop("num_procs", 1),
                **kwargs,
            )
        )
        db.session.commit()


def _delete(client, cluster_id, delete_outputs):
    resp = client.post(
        "/api/history/delete",
        json={"cluster_ids": [cluster_id], "delete_outputs": delete_outputs},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["results"][0]["success"] is True
    return resp.get_json()["results"][0]


def test_delete_outputs_finds_default_output_dir(
    secure_app, secure_client, monkeypatch
):
    monkeypatch.setattr("app.api.daemon_available", lambda: False)
    out_dir = Path(secure_app.config["OUTPUT_DIR"]) / "4321"
    out_dir.mkdir(parents=True)
    (out_dir / "frame.png").write_bytes(b"frame")
    (out_dir / "nested").mkdir()
    (out_dir / "nested" / "log.txt").write_text("log")
    _add_submission(secure_app, 4321)

    result = _delete(secure_client, 4321, True)

    assert result["deleted_output_files"] == 2
    assert not (out_dir / "frame.png").exists()
    assert not (out_dir / "nested" / "log.txt").exists()
    with secure_app.app_context():
        assert JobSubmission.query.filter_by(cluster_id=4321).first() is None


def test_delete_outputs_maps_osdf_destination(secure_app, secure_client, monkeypatch):
    monkeypatch.setattr("app.api.daemon_available", lambda: False)
    out_dir = Path(secure_app.config["OSDF_ROOT_PATH"]) / "outputs" / "4322"
    out_dir.mkdir(parents=True)
    (out_dir / "result.txt").write_text("result")
    _add_submission(
        secure_app,
        4322,
        output_destination=f"osdf:///chtc{out_dir}",
    )

    result = _delete(secure_client, 4322, True)

    assert result["deleted_output_files"] == 1
    assert not (out_dir / "result.txt").exists()


def test_delete_outputs_includes_remapped_files(secure_app, secure_client, monkeypatch):
    monkeypatch.setattr("app.api.daemon_available", lambda: False)
    remap_dir = Path(secure_app.extensions["test_dirs"]["tmp_path"]) / "remapped"
    remap_dir.mkdir()
    dest = remap_dir / "result.txt"
    dest.write_text("remapped")
    _add_submission(
        secure_app,
        4323,
        transfer_output_remaps=f"result.txt = {dest}",
    )

    result = _delete(secure_client, 4323, True)

    assert result["deleted_output_files"] == 1
    assert not dest.exists()


def test_remove_job_endpoint_can_delete_outputs(secure_app, secure_client, monkeypatch):
    monkeypatch.setattr("app.api.jobs.act_on_job", lambda *a, **k: None)
    out_dir = Path(secure_app.config["OUTPUT_DIR"]) / "4325"
    out_dir.mkdir(parents=True)
    output = out_dir / "frame.png"
    output.write_bytes(b"frame")
    _add_submission(secure_app, 4325)

    resp = secure_client.delete("/api/jobs/4325.0?delete_outputs=true")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["deleted_output_files"] == 1
    assert not output.exists()
    with secure_app.app_context():
        assert JobSubmission.query.filter_by(cluster_id=4325).first() is None


def test_delete_outputs_is_opt_in(secure_app, secure_client, monkeypatch):
    monkeypatch.setattr("app.api.daemon_available", lambda: False)
    out_dir = Path(secure_app.config["OUTPUT_DIR"]) / "4324"
    out_dir.mkdir(parents=True)
    output = out_dir / "keep.txt"
    output.write_text("keep")
    _add_submission(secure_app, 4324)

    result = _delete(secure_client, 4324, False)

    assert result["deleted_output_files"] == 0
    assert output.exists()
    with secure_app.app_context():
        assert JobSubmission.query.filter_by(cluster_id=4324).first() is None
