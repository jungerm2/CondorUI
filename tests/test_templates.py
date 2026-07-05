"""Tests for submit template CRUD operations and field preservation.

Templates are stored as .sub files on the filesystem. These tests verify
the backend API endpoints for templates: list, create, update, delete,
and field-level round-trip integrity.
"""

import json
import os
from pathlib import Path

# =============================================================================
# Sample submit descriptions for testing
# =============================================================================

SAMPLE_EXECUTABLE_SUBMIT = {
    "executable": "/bin/sleep",
    "arguments": "60",
    "universe": "vanilla",
    "request_cpus": "2",
    "request_memory": "2 GB",
    "request_disk": "4 GB",
    "output": "test.out",
    "error": "test.err",
    "log": "test.log",
    "transfer_input_files": "input1.txt, input2.dat",
    "transfer_output_files": "output.dat, results.tar.gz",
    "output_directory": "osdf:///chtc/staging/u/user/output",
    "transfer_output_remaps": (
        "output.dat = osdf:///chtc/staging/u/user/output.dat; "
        "results.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz"
    ),
    "MyCustomAttr": "custom_value",
    "AnotherAttr": "another_value",
}

SAMPLE_SHELL_SUBMIT = {
    "shell": "sleep 60",
    "universe": "vanilla",
    "request_cpus": "1",
    "request_memory": "1 GB",
    "request_disk": "1 GB",
}

SAMPLE_CONTAINER_SUBMIT = {
    "executable": "/bin/sleep",
    "arguments": "60",
    "universe": "container",
    "container_image": "osdf:///path/to/image.sif",
    "request_cpus": "1",
    "request_memory": "2 GB",
    "request_disk": "4 GB",
}

SAMPLE_GPU_SUBMIT = {
    "executable": "/bin/sleep",
    "universe": "vanilla",
    "request_cpus": "1",
    "request_memory": "2 GB",
    "request_disk": "4 GB",
    "request_gpus": "2",
    "gpus_minimum_capability": "8.5",
    "gpus_minimum_memory": "4 GB",
    "gpus_minimum_runtime": "9.1",
    "cuda_version": "11.0",
}

SAMPLE_RAW_TEXT = """universe = vanilla
executable = /bin/sleep
arguments = 60
request_cpus = 2
request_memory = 2 GB
request_disk = 4 GB
output = test.out
error = test.err
log = test.log
transfer_input_files = input1.txt, input2.dat
transfer_output_files = output.dat, results.tar.gz

queue 1"""


# =============================================================================
# Helpers
# =============================================================================


def _clean_templates_dir(app):
    """Remove all .json files from the templates directory."""
    templates_dir = Path(app.config["TEMPLATES_DIR"])
    for f in templates_dir.glob("*.json"):
        f.unlink()


# =============================================================================
# Tests: Basic CRUD
# =============================================================================


class TestTemplateCRUD:
    """Basic create, read, update, delete operations on templates."""

    def test_list_templates_empty(self, client, app):
        """GET /api/templates returns an empty list initially."""
        _clean_templates_dir(app)
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"templates": []}

    def test_create_template_with_json_submit_data(self, client, app):
        """POST /api/templates with JSON submit_data returns 201."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={
                "name": "My Template",
                "submit_data": SAMPLE_EXECUTABLE_SUBMIT,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My Template"
        assert json.loads(data["submit_data"]) == SAMPLE_EXECUTABLE_SUBMIT
        assert "updated_at" in data

    def test_create_template_with_raw_text(self, client, app):
        """POST /api/templates with raw text submit_data returns 201."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={"name": "Raw Template", "submit_data": SAMPLE_RAW_TEXT},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Raw Template"
        assert data["submit_data"] == SAMPLE_RAW_TEXT

    def test_create_template_missing_name(self, client, app):
        """POST /api/templates without name returns 400."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={"submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_template_missing_submit_data(self, client, app):
        """POST /api/templates without submit_data returns 400."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={"name": "No Data Template"},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_get_template_in_list_after_create(self, client, app):
        """Created template appears in the list response."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "Listable", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        resp = client.get("/api/templates")
        data = resp.get_json()
        assert len(data["templates"]) == 1
        assert data["templates"][0]["name"] == "Listable"

    def test_update_template_name(self, client, app):
        """PUT /api/templates/<name> updates the name."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "Original", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )

        update_resp = client.put(
            "/api/templates/Original",
            json={"name": "Updated Name"},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert data["name"] == "Updated Name"

    def test_update_template_submit_data(self, client, app):
        """PUT /api/templates/<name> updates submit_data (dict)."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "Data Update", "submit_data": SAMPLE_SHELL_SUBMIT},
        )

        update_resp = client.put(
            "/api/templates/Data Update",
            json={"submit_data": SAMPLE_CONTAINER_SUBMIT},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert json.loads(data["submit_data"]) == SAMPLE_CONTAINER_SUBMIT

    def test_update_template_submit_data_as_string(self, client, app):
        """PUT /api/templates/<name> updates submit_data (raw string)."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "String Data", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )

        new_raw = "universe = vanilla\nexecutable = /bin/ls\nqueue 1"
        update_resp = client.put(
            "/api/templates/String Data",
            json={"submit_data": new_raw},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert data["submit_data"] == new_raw

    def test_update_nonexistent_template(self, client, app):
        """PUT /api/templates/<bad_name> returns 404."""
        _clean_templates_dir(app)
        resp = client.put(
            "/api/templates/Nonexistent",
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404

    def test_delete_template(self, client, app):
        """DELETE /api/templates/<name> removes the template."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "Deletable", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )

        del_resp = client.delete("/api/templates/Deletable")
        assert del_resp.status_code == 200

        list_resp = client.get("/api/templates")
        assert len(list_resp.get_json()["templates"]) == 0

    def test_delete_nonexistent_template(self, client, app):
        """DELETE /api/templates/<bad_name> returns 404."""
        _clean_templates_dir(app)
        resp = client.delete("/api/templates/Nonexistent")
        assert resp.status_code == 404

    def test_template_name_unique_constraint(self, client, app):
        """POST with a duplicate name returns 409."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={"name": "Unique", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        resp = client.post(
            "/api/templates",
            json={"name": "Unique", "submit_data": SAMPLE_SHELL_SUBMIT},
        )
        assert resp.status_code == 409
        assert "error" in resp.get_json()


# =============================================================================
# Tests: Field Preservation
# =============================================================================


class TestTemplateFieldPreservation:
    """Ensure all submit fields are preserved through save/retrieve cycles."""

    def _create_and_retrieve(self, client, app, name: str, submit_data) -> dict:
        """Helper: create a template and retrieve it via GET list."""
        client.post(
            "/api/templates",
            json={"name": name, "submit_data": submit_data},
        )
        resp = client.get("/api/templates")
        templates = resp.get_json()["templates"]
        for t in templates:
            if t["name"] == name:
                return t
        raise AssertionError(f"Template '{name}' not found in list")

    def test_transfer_output_files_preserved(self, client, app):
        """transfer_output_files field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Output Files", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["transfer_output_files"] == "output.dat, results.tar.gz"

    def test_output_directory_preserved(self, client, app):
        """output_directory field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Output Dir", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["output_directory"] == "osdf:///chtc/staging/u/user/output"

    def test_transfer_output_remaps_preserved(self, client, app):
        """transfer_output_remaps field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Output Remaps", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert "transfer_output_remaps" in data
        assert "output.dat" in data["transfer_output_remaps"]
        assert "results.tar.gz" in data["transfer_output_remaps"]

    def test_transfer_input_files_preserved(self, client, app):
        """transfer_input_files field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Input Files", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["transfer_input_files"] == "input1.txt, input2.dat"

    def test_executable_and_arguments_preserved(self, client, app):
        """executable and arguments fields round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Exec", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["executable"] == "/bin/sleep"
        assert data["arguments"] == "60"

    def test_resource_requests_preserved(self, client, app):
        """request_cpus/memory/disk fields round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Resources", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["request_cpus"] == "2"
        assert data["request_memory"] == "2 GB"
        assert data["request_disk"] == "4 GB"

    def test_output_log_paths_preserved(self, client, app):
        """output, error, log paths round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Paths", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["output"] == "test.out"
        assert data["error"] == "test.err"
        assert data["log"] == "test.log"

    def test_custom_classads_preserved(self, client, app):
        """Custom ClassAd attributes round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Custom", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["MyCustomAttr"] == "custom_value"
        assert data["AnotherAttr"] == "another_value"

    def test_shell_command_preserved(self, client, app):
        """Shell-mode submit data round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Shell", SAMPLE_SHELL_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["shell"] == "sleep 60"
        assert "executable" not in data

    def test_container_universe_preserved(self, client, app):
        """Container universe + container_image round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Container", SAMPLE_CONTAINER_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["universe"] == "container"
        assert data["container_image"] == "osdf:///path/to/image.sif"

    def test_gpu_fields_preserved(self, client, app):
        """All GPU/CUDA fields round-trip correctly."""
        tmpl = self._create_and_retrieve(
            client, app, "Gpu", SAMPLE_GPU_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["request_gpus"] == "2"
        assert data["gpus_minimum_capability"] == "8.5"
        assert data["gpus_minimum_memory"] == "4 GB"
        assert data["gpus_minimum_runtime"] == "9.1"
        assert data["cuda_version"] == "11.0"

    def test_raw_text_preserved(self, client, app):
        """Raw text submit_data round-trips verbatim."""
        tmpl = self._create_and_retrieve(
            client, app, "Raw Text", SAMPLE_RAW_TEXT
        )
        assert tmpl["submit_data"] == SAMPLE_RAW_TEXT

    def test_full_submit_dict_round_trip(self, client, app):
        """Every key in the submit dict survives save and retrieve."""
        _clean_templates_dir(app)
        submit_data = {
            "executable": "/bin/echo",
            "arguments": "hello world",
            "universe": "vanilla",
            "request_cpus": "4",
            "request_memory": "8 GB",
            "request_disk": "16 GB",
            "output": "out.txt",
            "error": "err.txt",
            "log": "job.log",
            "transfer_input_files": "a.dat, b.dat",
            "transfer_output_files": "result.dat",
            "output_directory": "osdf:///test/output",
            "transfer_output_remaps": ("result.dat = osdf:///test/output/result.dat"),
            "should_transfer_files": "YES",
            "when_to_transfer_output": "ON_EXIT",
            "notification": "Always",
            "Requirements": "(Target.HasCHTCStaging == true)",
            "MyCustom": "custom_val",
            "AnotherCustom": "12345",
        }

        resp = client.post(
            "/api/templates",
            json={"name": "Full Dict", "submit_data": submit_data},
        )
        assert resp.status_code == 201
        saved = json.loads(resp.get_json()["submit_data"])

        for key, value in submit_data.items():
            assert saved.get(key) == value, (
                f"Key {key!r}: expected {value!r}, got {saved.get(key)!r}"
            )

    def test_submit_data_is_valid_json(self, client, app):
        """submit_data stored by the API is always valid JSON when dict input given."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={
                "name": "Valid JSON",
                "submit_data": SAMPLE_EXECUTABLE_SUBMIT,
            },
        )
        data = resp.get_json()
        # Should not raise
        parsed = json.loads(data["submit_data"])
        assert isinstance(parsed, dict)
        assert parsed["executable"] == "/bin/sleep"

    def test_all_form_fields_round_trip(self, client, app):
        """Every form field in the submit UI survives save and retrieve.

        This is the canonical list of all fields that the Form Builder mode
        can produce.  If a new field is added to the form, it must be added
        here AND in checkSelectedTemplate() in submit.js.
        """
        _clean_templates_dir(app)
        all_fields = {
            "executable": "/bin/echo",
            "arguments": "hello world",
            "universe": "vanilla",
            "request_cpus": "4",
            "request_memory": "8 GB",
            "request_disk": "16 GB",
            "output": "out.txt",
            "error": "err.txt",
            "log": "job.log",
            "transfer_input_files": "a.dat, b.dat",
            "transfer_output_files": "result.dat",
            "output_directory": "osdf:///test/output",
            "transfer_output_remaps": "result.dat = osdf:///test/output/result.dat",
            "request_gpus": "2",
            "gpus_minimum_capability": "8.5",
            "gpus_minimum_memory": "4 GB",
            "gpus_minimum_runtime": "9.1",
            "cuda_version": "11.0",
            "should_transfer_files": "YES",
            "when_to_transfer_output": "ON_EXIT",
            "notification": "Always",
            "Requirements": "(Target.HasCHTCStaging == true)",
            "MyCustom": "custom_val",
            "AnotherCustom": "12345",
        }

        resp = client.post(
            "/api/templates",
            json={"name": "All Fields", "submit_data": all_fields},
        )
        assert resp.status_code == 201
        saved = json.loads(resp.get_json()["submit_data"])

        for key, value in all_fields.items():
            assert saved.get(key) == value, (
                f"Key {key!r}: expected {value!r}, got {saved.get(key)!r}"
            )

        # Also verify via GET list
        list_resp = client.get("/api/templates")
        tmpl = next(
            t for t in list_resp.get_json()["templates"] if t["name"] == "All Fields"
        )
        retrieved = json.loads(tmpl["submit_data"])
        for key, value in all_fields.items():
            assert retrieved.get(key) == value, (
                f"Key {key!r} via GET: expected {value!r}, got {retrieved.get(key)!r}"
            )


# =============================================================================
# Tests: Timestamps and Ordering
# =============================================================================


class TestTemplateTimestamps:
    """Timestamp-related behavior for templates (using filesystem mtime)."""

    def test_updated_at_set_on_create(self, client, app):
        """updated_at is set on template creation."""
        _clean_templates_dir(app)
        resp = client.post(
            "/api/templates",
            json={"name": "Timed", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        data = resp.get_json()
        assert data["updated_at"] is not None
        # Should be a valid ISO datetime
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(data["updated_at"].rstrip("Z")).replace(
            tzinfo=timezone.utc
        )
        # Should be recent (within last 10 seconds)
        now = datetime.now(timezone.utc)
        assert (now - dt).total_seconds() < 10

    def test_updated_at_changes_on_update(self, client, app):
        """updated_at changes after a PUT that modifies content."""
        _clean_templates_dir(app)
        import time as _time

        create_resp = client.post(
            "/api/templates",
            json={"name": "ChangeMe", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        original_updated = create_resp.get_json()["updated_at"]

        _time.sleep(0.1)  # Ensure mtime changes (filesystem granularity)
        # Update submit_data (not just rename) to force mtime change
        update_resp = client.put(
            "/api/templates/ChangeMe",
            json={"submit_data": SAMPLE_SHELL_SUBMIT},
        )
        new_updated = update_resp.get_json()["updated_at"]

        assert new_updated != original_updated

    def test_list_ordered_by_updated_at_desc(self, client, app):
        """Templates are listed in descending order of updated_at."""
        _clean_templates_dir(app)
        import time as _time

        client.post(
            "/api/templates",
            json={"name": "First", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        _time.sleep(0.01)
        client.post(
            "/api/templates",
            json={"name": "Second", "submit_data": SAMPLE_SHELL_SUBMIT},
        )
        _time.sleep(0.01)
        client.post(
            "/api/templates",
            json={"name": "Third", "submit_data": SAMPLE_CONTAINER_SUBMIT},
        )

        resp = client.get("/api/templates")
        templates = resp.get_json()["templates"]
        names = [t["name"] for t in templates]
        assert names == ["Third", "Second", "First"]


# =============================================================================
# Tests: Update Behavior
# =============================================================================


class TestTemplateUpdateBehavior:
    """Fine-grained update behavior tests."""

    def test_partial_update_name_only(self, client, app):
        """PUT only updating name preserves submit_data."""
        _clean_templates_dir(app)
        original_submit = dict(SAMPLE_EXECUTABLE_SUBMIT)
        client.post(
            "/api/templates",
            json={
                "name": "Partial",
                "submit_data": original_submit,
            },
        )

        # Update only the name
        client.put("/api/templates/Partial", json={"name": "Renamed"})

        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.get_json()["templates"] if t["name"] == "Renamed")
        assert tmpl["name"] == "Renamed"
        assert json.loads(tmpl["submit_data"]) == original_submit

    def test_partial_update_submit_data_only(self, client, app):
        """PUT only updating submit_data preserves name."""
        _clean_templates_dir(app)
        client.post(
            "/api/templates",
            json={
                "name": "Fixname",
                "submit_data": SAMPLE_SHELL_SUBMIT,
            },
        )

        # Update only submit_data
        new_submit = {"executable": "/bin/ls", "universe": "vanilla"}
        client.put(
            "/api/templates/Fixname",
            json={"submit_data": new_submit},
        )

        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.get_json()["templates"] if t["name"] == "Fixname")
        assert tmpl["name"] == "Fixname"
        assert json.loads(tmpl["submit_data"]) == new_submit
