"""Playwright smoke tests for the dashboard page.

Covers the dashboard_render.js / dashboard.js split: loads the unified jobs
table in a real browser and asserts the page renders without JS errors,
including the grouped (cluster) view that exercises the extracted helpers
(groupJobs, getGroupSortValue, renderStatusBar).
"""

import json


def _seed_submission(app, cluster_id=101, num_procs=2, name="Smoke Job"):
    from app import db
    from app.models import JobSubmission

    with app.app_context():
        db.session.add(
            JobSubmission(
                cluster_id=cluster_id,
                name=name,
                submit_description=json.dumps(
                    {"executable": "/bin/sleep", "arguments": "10"}
                ),
                num_procs=num_procs,
            )
        )
        db.session.commit()


def _clear_seeds(app, cluster_ids):
    """Remove rows seeded by these tests — the app DB is session-scoped."""
    from app import db
    from app.models import JobSubmission

    with app.app_context():
        JobSubmission.query.filter(JobSubmission.cluster_id.in_(cluster_ids)).delete(
            synchronize_session=False
        )
        db.session.commit()


def _stub_no_daemon(monkeypatch):
    """Avoid multi-minute schedd connect timeouts in the test environment."""
    monkeypatch.setattr("app.api.daemon_available", lambda: False)


class TestDashboardUI:
    def test_dashboard_renders_without_js_errors(
        self, page, live_server, app, monkeypatch, request
    ):
        _stub_no_daemon(monkeypatch)
        _seed_submission(app)
        request.addfinalizer(lambda: _clear_seeds(app, [101]))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{live_server}/")
        page.wait_for_selector("#jobs-tbody tr", timeout=10_000)

        # The seeded cluster group renders (grouped view is the default).
        body_text = page.inner_text("#jobs-tbody")
        assert "Smoke Job" in body_text
        assert "101" in body_text

        assert not errors, f"JS errors on dashboard: {errors}"
        _clear_seeds(app, [101])

    def test_flat_view_and_search(self, page, live_server, app, monkeypatch, request):
        _stub_no_daemon(monkeypatch)
        _seed_submission(app, cluster_id=202, name="Findable Job")
        _seed_submission(app, cluster_id=203, name="Other Job")
        request.addfinalizer(lambda: _clear_seeds(app, [202, 203]))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{live_server}/")
        page.wait_for_selector("#jobs-tbody tr", timeout=10_000)

        # Switch to flat (non-grouped) view — exercises getSortValue path.
        # The checkbox itself is visually hidden; click its label instead.
        page.click("#group-toggle-label")
        page.wait_for_timeout(300)

        # Search filters client-side — exercises matchesJobFilter.
        page.fill("#job-search", "Findable")
        page.wait_for_timeout(500)

        body_text = page.inner_text("#jobs-tbody")
        assert "Findable Job" in body_text
        assert "Other Job" not in body_text

        assert not errors, f"JS errors on dashboard: {errors}"
        _clear_seeds(app, [202, 203])
