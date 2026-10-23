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


class TestSidebarUI:
    def test_brand_theme_and_collapse_controls(self, page, live_server):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{live_server}/output-files")
        page.wait_for_selector(".brand-mark", timeout=10_000)

        # The brand is its own home link; the theme control is a footer utility.
        assert page.locator("a.logo[href='/'] .brand-mark").count() == 1
        assert page.locator(".logo #theme-toggle").count() == 0
        assert page.locator(".sidebar-footer #theme-toggle").count() == 1
        assert (
            page.locator("link[rel='icon']").get_attribute("href")
            == "/static/favicon.svg"
        )
        assert page.request.get(f"{live_server}/static/favicon.svg").ok

        button = page.locator("#sidebar-collapse-btn")
        box = button.bounding_box()
        assert box is not None
        assert box["width"] >= 32 and box["height"] >= 32

        footer = page.evaluate(
            """() => {
                const connection = document.querySelector('.connection-status').getBoundingClientRect();
                const theme = document.querySelector('#theme-toggle').getBoundingClientRect();
                return {
                    connectionRight: connection.right,
                    themeLeft: theme.left,
                    sameRow: Math.abs(
                        (connection.top + connection.height / 2) -
                        (theme.top + theme.height / 2)
                    ) < 1,
                };
            }"""
        )
        assert footer["sameRow"], footer
        assert footer["themeLeft"] > footer["connectionRight"], footer
        assert page.locator(".theme-label").is_visible()

        page.click("#sidebar-collapse-btn")
        page.wait_for_timeout(250)
        state = page.evaluate("""() => {
            const brand = document.querySelector('.brand-mark').getBoundingClientRect();
            const buttonEl = document.querySelector('#sidebar-collapse-btn');
            const button = buttonEl.getBoundingClientRect();
            const themeEl = document.querySelector('#theme-toggle');
            const theme = themeEl.getBoundingClientRect();
            return {
                brandBottom: brand.bottom,
                buttonTop: button.top,
                buttonWidth: button.width,
                buttonHeight: button.height,
                buttonOpacity: getComputedStyle(buttonEl).opacity,
                buttonDisplay: getComputedStyle(buttonEl).display,
                buttonAriaExpanded: buttonEl.getAttribute('aria-expanded'),
                sidebarWidth: document.querySelector('#sidebar').getBoundingClientRect().width,
                themeWidth: theme.width,
                themeHeight: theme.height,
                themeLabelDisplay: getComputedStyle(document.querySelector('.theme-label')).display,
            };
        }""")
        assert state["buttonTop"] >= state["brandBottom"], state
        assert state["buttonWidth"] >= 32 and state["buttonHeight"] >= 32, state
        assert state["buttonOpacity"] == "1", state
        assert state["buttonDisplay"] == "flex", state
        assert state["buttonAriaExpanded"] == "false", state
        assert state["sidebarWidth"] == 60, state
        assert state["themeWidth"] >= 32 and state["themeHeight"] >= 32, state
        assert state["themeLabelDisplay"] == "none", state

        was_light = page.evaluate(
            "document.documentElement.classList.contains('light-theme')"
        )
        page.click("#theme-toggle")
        page.wait_for_timeout(100)
        is_light = page.evaluate(
            "document.documentElement.classList.contains('light-theme')"
        )
        assert is_light != was_light
        label = page.locator(".theme-label").text_content()
        assert label == ("Light mode" if is_light else "Dark mode")
        assert not errors, f"JS errors on sidebar: {errors}"
