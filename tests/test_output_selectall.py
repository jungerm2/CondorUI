"""Select-all on the output-files page must key selections by cluster/filename.

Regression: the select-all handler keyed the selection by bare filename
while every other code path used ``outputKey()`` (``cluster_id/filename``),
so the header checkbox never reflected the selection and clicking it
re-selected instead of clearing.
"""

import json
from pathlib import Path

from app import db
from app.models import JobSubmission

STATE_JS = """() => {
    const a = document.querySelector('#output-select-all');
    const rows = [...document.querySelectorAll('.output-row-checkbox')];
    return {checked: a.checked, indeterminate: a.indeterminate,
            rows: rows.map(r => r.checked)};
}"""


def _clear_seed(app, cluster_id=90101):
    """The app DB is session-scoped across test files — remove what we added."""
    with app.app_context():
        JobSubmission.query.filter_by(cluster_id=cluster_id).delete(
            synchronize_session=False
        )
        db.session.commit()


def test_output_select_all_deselects(page, live_server, app, request):
    out_dir = Path(app.config["OUTPUT_DIR"]) / "90101"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "job0.out").write_bytes(b"out0")
    (out_dir / "job1.out").write_bytes(b"out1")

    with app.app_context():
        db.session.add(
            JobSubmission(
                cluster_id=90101,
                name="SelectAll Job",
                submit_description=json.dumps(
                    {"executable": "/bin/sleep", "arguments": "1"}
                ),
                num_procs=1,
                output_destination=str(out_dir),
            )
        )
        db.session.commit()
    request.addfinalizer(lambda: _clear_seed(app))

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{live_server}/output-files")
    page.wait_for_selector(".output-row-checkbox", timeout=10_000)

    page.click("#output-select-all")
    page.wait_for_timeout(200)
    state = page.evaluate(STATE_JS)
    assert state["checked"] and not state["indeterminate"], state
    assert all(state["rows"]), state

    # Grouped view: one collapsible header per cluster with job name
    headers = page.locator("tr.group-header[data-cluster-id='90101']")
    assert headers.count() == 1, "output files must render grouped by job"
    assert "SelectAll Job" in headers.first.inner_text()
    assert "2 files ·" in headers.first.inner_text()

    page.click("#output-select-all")  # second click must deselect everything
    page.wait_for_timeout(200)
    state = page.evaluate(STATE_JS)
    assert state == {
        "checked": False,
        "indeterminate": False,
        "rows": [False, False],
    }, state

    assert not errors, f"JS errors on output-files: {errors}"
