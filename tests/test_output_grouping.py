"""Output groups read like jobs: newest first, with the expander on the right."""

import json
import os
import shutil
from pathlib import Path

from app import db
from app.models import JobSubmission


def _seed_job(app, cluster_id, name, out_dir, mtime):
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "output.txt"
    file_path.write_text(name)
    os.utime(file_path, (mtime, mtime))
    with app.app_context():
        db.session.add(
            JobSubmission(
                cluster_id=cluster_id,
                name=name,
                submit_description=json.dumps({"executable": "/bin/true"}),
                num_procs=1,
                output_destination=str(out_dir),
            )
        )
        db.session.commit()


def test_groups_sort_newest_first_and_expander_is_right(
    page, live_server, app, request
):
    output_root = Path(app.config["OUTPUT_DIR"])
    newer_dir = output_root / "90201"
    older_dir = output_root / "90202"
    _seed_job(app, 90201, "Newer job", newer_dir, 1_800_000_000)
    _seed_job(app, 90202, "Older job", older_dir, 1_700_000_000)

    def cleanup():
        with app.app_context():
            JobSubmission.query.filter(
                JobSubmission.cluster_id.in_([90201, 90202])
            ).delete(synchronize_session=False)
            db.session.commit()
        shutil.rmtree(newer_dir, ignore_errors=True)
        shutil.rmtree(older_dir, ignore_errors=True)

    request.addfinalizer(cleanup)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/output-files")
    page.wait_for_selector("tr.group-header", timeout=10_000)

    headers = page.locator("tr.group-header")
    texts = headers.all_inner_texts()
    assert "Newer job" in texts[0], texts
    assert "Older job" in texts[1], texts

    geometry = page.evaluate(
        """() => {
            const row = document.querySelector('tr.group-header');
            const group = row.querySelector('.output-group-header');
            const chevron = row.querySelector('.expand-chevron');
            const rowBox = row.getBoundingClientRect();
            const chevronBox = chevron.getBoundingClientRect();
            return {
                isLast: group.lastElementChild === chevron,
                rowLeft: rowBox.left,
                rowWidth: rowBox.width,
                chevronRight: chevronBox.right,
            };
        }"""
    )
    assert geometry["isLast"], "expander must be the last item in the header"
    assert (
        geometry["chevronRight"] > geometry["rowLeft"] + geometry["rowWidth"] * 0.8
    ), geometry
    assert not errors, f"JS errors on output-files: {errors}"
