"""Regression tests for fixed bugs:

- qedit rejecting legitimate falsy values (e.g., ``value: 0``)
- rename_file working on OSDF-staged files
- daemon_available probe memoization resets with clear_cache()
- quota File_Limit "N/A" renders as null (no trailing "/ N/A" on cards)
"""

import subprocess


class TestQeditFalsyValue:
    def test_qedit_accepts_zero_value(self, client, monkeypatch):
        """``value: 0`` is valid — must be forwarded, not rejected as missing."""
        captured = {}

        def fake_qedit(cluster_id, proc_id, attr, value):
            captured.update(
                cluster_id=cluster_id, proc_id=proc_id, attr=attr, value=value
            )
            return {"action": "qedit", "result": "ok"}

        monkeypatch.setattr("app.api.jobs.qedit_job", fake_qedit)
        resp = client.post(
            "/api/qedit",
            json={"cluster_id": 123, "proc_id": 0, "attr": "RequestDisk", "value": 0},
        )
        assert resp.status_code == 200, resp.get_json()
        assert captured["value"] == 0

    def test_qedit_rejects_missing_value(self, client):
        resp = client.post(
            "/api/qedit", json={"cluster_id": 123, "attr": "RequestDisk"}
        )
        assert resp.status_code == 400


class TestRenameStagedFile:
    def test_rename_staged_file(self, secure_app, secure_client):
        osdf_uploads = secure_app.extensions["test_dirs"]["osdf_root"] / "uploads"
        staged = osdf_uploads / "u1" / "staged.txt"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"staged")

        resp = secure_client.put(
            "/api/files/u1/staged.txt", json={"filename": "renamed.txt"}
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["osdf_path"] is not None
        assert body["uri"].startswith("osdf:///")
        assert body["local_path"] is None
        assert not staged.exists()
        assert (osdf_uploads / "u1" / "renamed.txt").exists()


class TestLogFileTailing:
    """get_job_file_content reads only a bounded suffix of the file."""

    def test_tail_returns_last_lines(self, tmp_path):
        from app.condor import get_job_file_content

        f = tmp_path / "log.txt"
        f.write_text("".join(f"line {i}\n" for i in range(1000)))
        out = get_job_file_content(str(f), tail=5)
        assert out.splitlines() == [f"line {i}" for i in range(995, 1000)]

    def test_missing_file_returns_empty(self, tmp_path):
        from app.condor import get_job_file_content

        assert get_job_file_content(str(tmp_path / "nope.log")) == ""
        assert get_job_file_content("") == ""

    def test_huge_file_read_is_capped(self, tmp_path):
        from app.condor import MAX_TAIL_BYTES, get_job_file_content

        f = tmp_path / "big.log"
        f.write_text("x" * (300 * 1024) + "\nlast\n")  # ~300 KiB
        out = get_job_file_content(str(f), tail=10)
        # The truncated first line is dropped; only whole lines remain.
        assert out == "last\n"
        assert len(out) <= MAX_TAIL_BYTES


class TestDaemonProbeMemoization:
    def test_clear_cache_resets_probe(self):
        # _daemon_probe is module state; clear_cache must reset it so
        # stale availability doesn't leak between operations/tests.
        from app.condor import clear_cache

        clear_cache()
        from app import condor as condor_module

        assert condor_module._daemon_probe is None


class TestDetailsWithoutSchedd:
    def test_details_degrades_when_schedd_errors(self, client, monkeypatch):
        """`/api/jobs/<id>/details` must serve DB fallback data (200), not 500.

        htcondor2's Schedd() constructor can raise when no local daemon is
        configured; that used to happen outside the endpoint's try block.
        """
        import app.condor as condor_module

        def boom(*args, **kwargs):
            raise RuntimeError("Unable to locate local daemon")

        monkeypatch.setattr(condor_module, "get_schedd", boom)
        monkeypatch.setattr("app.api.daemon_available", lambda: False)

        resp = client.get("/api/jobs/123/details")
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["cluster_id"] == 123


class TestQuotaNaLimit:
    def test_na_file_limit_returns_null(self, client, monkeypatch):
        """get_quotas prints N/A when there is no limit; the endpoint must
        send null so cards render "80,572 files" without a trailing "/ N/A"."""

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "Path Disk_Used(GB) Disk_Limit(GB) Files_Used File_Limit\n"
                    "/home/u 30.65 40.00 80572 N/A\n"
                    "/staging/u 11.16 100.00 79 100\n"
                ),
                stderr="",
            )

        monkeypatch.setattr("app.api.quotas.subprocess.run", fake_run)
        resp = client.get("/api/quotas")
        assert resp.status_code == 200
        quotas = resp.get_json()["quotas"]
        assert quotas[0]["file_limit"] is None
        assert quotas[0]["disk_used_gb"] == 30.65
        assert quotas[0]["files_used"] == 80572
        assert quotas[1]["file_limit"] == 100


class TestRouteRegistration:
    def test_history_delete_route_registered(self, client):
        # Regression guard: a route decorator was once accidentally dropped,
        # making /api/history/delete 404 with no test failing.
        resp = client.post("/api/history/delete", json={})
        assert resp.status_code == 400  # reachable; rejects missing cluster_ids
        assert "cluster_ids" in resp.get_json()["error"]

    def test_api_route_count(self, app):
        # Guards against silently losing routes during refactors.
        n = len([r for r in app.url_map.iter_rules() if str(r).startswith("/api")])
        assert n == 55, f"expected 55 API routes, found {n}"
