"""Tests for /api/history pagination semantics.

The history endpoint paginates by **cluster** when ``grouped=1`` (each page
shows ``limit`` clusters with ALL of their procs expanded) and by individual
**proc** when ``grouped=0`` (flat view). These tests verify the
``total``/``has_more``/``jobs`` shape for both modes.

The schedd is stubbed out (``daemon_available`` -> ``False``) so the tests
exercise the local-DB history path deterministically.
"""

from datetime import UTC, datetime

import pytest

from app import db
from app.models import JobSubmission


def _ts(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _terminated_event(cluster_id: int, proc_id: int, when: str, rc: int) -> str:
    return f"""005 ({cluster_id}.{proc_id:03d}.000) {when} Job terminated.
    (1) Normal termination (return value {rc})
        Usr 0 00:00:00, Sys 0 00:00:00  -  Run Remote Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Run Local Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Total Remote Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Total Local Usage
    0  -  Run Bytes Sent By Job
    27848  -  Run Bytes Received By Job
    0  -  Total Bytes Sent By Job
    27848  -  Total Bytes Received By Job
    Partitionable Resources :    Usage  Request Allocated
       Cpus                 :                 1         1
       Disk (KB)            :       40       30   4203309
       Memory (MB)          :        1        1         1
...
"""


@pytest.fixture
def no_daemon(monkeypatch):
    monkeypatch.setattr("app.api.daemon_available", lambda: False)


@pytest.fixture
def sample_subs(app):
    """Three clusters with procs 2, 3, 1  => 6 procs, 3 clusters.

    submitted_at is ordered so the cluster order (desc by submitted_at) is
    [12, 11, 10] with proc counts [1, 3, 2].
    """
    with app.app_context():
        db.session.add_all(
            [
                JobSubmission(
                    cluster_id=10,
                    name="job-10",
                    owner="alice",
                    num_procs=2,
                    submitted_at=_ts(1600000000),
                    submit_description="{}",
                ),
                JobSubmission(
                    cluster_id=11,
                    name="job-11",
                    owner="alice",
                    num_procs=3,
                    submitted_at=_ts(1600000001),
                    submit_description="{}",
                ),
                JobSubmission(
                    cluster_id=12,
                    name="job-12",
                    owner="alice",
                    num_procs=1,
                    submitted_at=_ts(1600000002),
                    submit_description="{}",
                ),
            ]
        )
        db.session.commit()
    yield [10, 11, 12]


def _fetch(app, query):
    resp = app.test_client().get(f"/api/history{query}")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def test_grouped_paginates_by_cluster(app, sample_subs, no_daemon):
    # Page 1: first `limit` (2) clusters -> clusters 12 (1 proc) + 11 (3 procs)
    d = _fetch(app, "?grouped=1&limit=2&offset=0")
    assert d["total"] == 3  # 3 clusters, not 6 procs
    assert d["has_more"] is True
    assert len(d["jobs"]) == 4  # all procs of the first 2 clusters

    # Page 2: remaining 1 cluster (2 procs)
    d = _fetch(app, "?grouped=1&limit=2&offset=2")
    assert d["total"] == 3
    assert d["has_more"] is False
    assert len(d["jobs"]) == 2


def test_flat_paginates_by_proc(app, sample_subs, no_daemon):
    # Page 1: first 2 procs
    d = _fetch(app, "?grouped=0&limit=2&offset=0")
    assert d["total"] == 6  # 6 procs
    assert d["has_more"] is True
    assert len(d["jobs"]) == 2

    # Last page: procs at offset 4..5
    d = _fetch(app, "?grouped=0&limit=2&offset=4")
    assert d["total"] == 6
    assert d["has_more"] is False
    assert len(d["jobs"]) == 2


def test_default_grouped_is_proc_level(app, sample_subs, no_daemon):
    # Omitting `grouped` falls back to proc-level pagination.
    d = _fetch(app, "?limit=2&offset=0")
    assert d["total"] == 6
    assert d["has_more"] is True
    assert len(d["jobs"]) == 2


def test_history_list_never_scans_schedd_history(app, sample_subs, monkeypatch):
    """The dashboard list must render from the DB + active queue only.

    It used to run a constrained ``schedd.history`` scan on every load and
    auto-refresh to fill completion dates (fe35348).  Matching an OR of a
    page's cluster ids walks the history file from newest to oldest, which
    takes far longer than fetching the newest N rows — on a real history it
    exceeded the 15s query timeout and blocked every other schedd call.
    """
    import app.condor as condor_module

    monkeypatch.setattr("app.api.daemon_available", lambda: True)
    monkeypatch.setattr("app.api.history.query_jobs", lambda **kwargs: [])

    submits: list[tuple] = []
    monkeypatch.setattr(
        condor_module._schedd_executor,
        "submit",
        lambda *args, **kwargs: submits.append(args),
    )

    resp = app.test_client().get("/api/history?grouped=1&limit=2")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 4  # clusters 12 (1 proc) + 11 (3 procs)
    assert submits == []


def test_history_fills_completion_fields_from_userlog(app, no_daemon, tmp_path):
    """Completed rows get their finish facts from the job's own UserLog."""
    log_path = tmp_path / "4242.log"
    log_path.write_text(
        "001 (4242.000.000) 2020-07-10 10:45:00 Job executing on host: <x>\n"
        "...\n" + _terminated_event(4242, 0, "2020-07-10 10:46:00", 0)
    )

    with app.app_context():
        db.session.add(
            JobSubmission(
                cluster_id=4242,
                name="finished-job",
                owner="alice",
                num_procs=1,
                submitted_at=_ts(1800000000),
                submit_description="{}",
                log_path=str(log_path),
            )
        )
        db.session.commit()

    try:
        data = _fetch(app, "?grouped=0&limit=10")
        job = next(j for j in data["jobs"] if j["ClusterId"] == 4242)
        assert job["CompletionDate"] == int(datetime(2020, 7, 10, 10, 46).timestamp())
        assert job["LastRemoteWallClockTime"] == 60
        assert job["ExitCode"] == 0
    finally:
        # This app fixture shares an in-memory DB across the session.
        with app.app_context():
            JobSubmission.query.filter_by(cluster_id=4242).delete()
            db.session.commit()
