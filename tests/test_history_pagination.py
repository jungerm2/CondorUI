"""Tests for /api/history pagination semantics.

The history endpoint paginates by **cluster** when ``grouped=1`` (each page
shows ``limit`` clusters with ALL of their procs expanded) and by individual
**proc** when ``grouped=0`` (flat view). These tests verify the
``total``/``has_more``/``jobs`` shape for both modes.

The schedd is stubbed out (``daemon_available`` -> ``False``) so the tests
exercise the local-DB history path deterministically.
"""

from datetime import datetime, timezone

import pytest

from app import db
from app.models import JobSubmission


def _ts(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


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
