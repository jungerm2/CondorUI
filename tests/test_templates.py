"""Tests for submit template CRUD operations and field preservation.

Template loading and saving should preserve all submit fields exactly.
These tests verify the backend API endpoints for templates: list, create,
update, delete, and field-level round-trip integrity.
"""

import json
from datetime import datetime, timezone

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


def _sorted_template_keys(t: dict) -> dict:
    """Return template dict with keys sorted (for predictable comparison)."""
    return {k: t[k] for k in sorted(t.keys())}


def _datetime_from_iso(iso_str: str) -> datetime:
    """Parse an ISO 8601 datetime string (with 'Z' suffix)."""
    return datetime.fromisoformat(iso_str.rstrip("Z")).replace(tzinfo=timezone.utc)


# =============================================================================
# Tests: Basic CRUD
# =============================================================================


class TestTemplateCRUD:
    """Basic create, read, update, delete operations on templates."""

    def test_list_templates_empty(self, client, db):
        """GET /api/templates returns an empty list initially."""
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"templates": []}

    def test_create_template_with_json_submit_data(self, client, db):
        """POST /api/templates with JSON submit_data returns 201."""
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
        assert data["id"] > 0
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_template_with_raw_text(self, client, db):
        """POST /api/templates with raw text submit_data returns 201."""
        resp = client.post(
            "/api/templates",
            json={"name": "Raw Template", "submit_data": SAMPLE_RAW_TEXT},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Raw Template"
        assert data["submit_data"] == SAMPLE_RAW_TEXT

    def test_create_template_missing_name(self, client, db):
        """POST /api/templates without name returns 400."""
        resp = client.post(
            "/api/templates",
            json={"submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_template_missing_submit_data(self, client, db):
        """POST /api/templates without submit_data returns 400."""
        resp = client.post(
            "/api/templates",
            json={"name": "No Data Template"},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_create_template_with_description(self, client, db):
        """POST /api/templates includes optional description."""
        resp = client.post(
            "/api/templates",
            json={
                "name": "Described Template",
                "description": "A useful description",
                "submit_data": SAMPLE_EXECUTABLE_SUBMIT,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["description"] == "A useful description"

    def test_get_template_in_list_after_create(self, client, db):
        """Created template appears in the list response."""
        client.post(
            "/api/templates",
            json={"name": "Listable", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        resp = client.get("/api/templates")
        data = resp.get_json()
        assert len(data["templates"]) == 1
        assert data["templates"][0]["name"] == "Listable"

    def test_update_template_name(self, client, db):
        """PUT /api/templates/<id> updates the name."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "Original", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]

        update_resp = client.put(
            f"/api/templates/{tmpl_id}",
            json={"name": "Updated Name"},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert data["name"] == "Updated Name"

    def test_update_template_submit_data(self, client, db):
        """PUT /api/templates/<id> updates submit_data (dict)."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "Data Update", "submit_data": SAMPLE_SHELL_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]

        update_resp = client.put(
            f"/api/templates/{tmpl_id}",
            json={"submit_data": SAMPLE_CONTAINER_SUBMIT},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert json.loads(data["submit_data"]) == SAMPLE_CONTAINER_SUBMIT

    def test_update_template_submit_data_as_string(self, client, db):
        """PUT /api/templates/<id> updates submit_data (raw string)."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "String Data", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]

        new_raw = "universe = vanilla\nexecutable = /bin/ls\nqueue 1"
        update_resp = client.put(
            f"/api/templates/{tmpl_id}",
            json={"submit_data": new_raw},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert data["submit_data"] == new_raw

    def test_update_template_description(self, client, db):
        """PUT /api/templates/<id> updates description."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "Desc Update", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]

        update_resp = client.put(
            f"/api/templates/{tmpl_id}",
            json={"description": "New description"},
        )
        assert update_resp.status_code == 200
        data = update_resp.get_json()
        assert data["description"] == "New description"

    def test_update_nonexistent_template(self, client, db):
        """PUT /api/templates/<bad_id> returns 404."""
        resp = client.put(
            "/api/templates/99999",
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404

    def test_delete_template(self, client, db):
        """DELETE /api/templates/<id> removes the template."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "Deletable", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]

        del_resp = client.delete(f"/api/templates/{tmpl_id}")
        assert del_resp.status_code == 200

        list_resp = client.get("/api/templates")
        assert len(list_resp.get_json()["templates"]) == 0

    def test_delete_nonexistent_template(self, client, db):
        """DELETE /api/templates/<bad_id> returns 404."""
        resp = client.delete("/api/templates/99999")
        assert resp.status_code == 404

    def test_template_name_unique_constraint(self, client, db):
        """POST with a duplicate name returns 400 or 500 (integrity error)."""
        client.post(
            "/api/templates",
            json={"name": "Unique", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        resp = client.post(
            "/api/templates",
            json={"name": "Unique", "submit_data": SAMPLE_SHELL_SUBMIT},
        )
        # SQLite unique constraint violation returns an error
        assert resp.status_code in (400, 409, 500)
        assert "error" in resp.get_json()


# =============================================================================
# Tests: Field Preservation
# =============================================================================


class TestTemplateFieldPreservation:
    """Ensure all submit fields are preserved through save/retrieve cycles."""

    def _create_and_retrieve(self, client, name: str, submit_data) -> dict:
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

    def test_transfer_output_files_preserved(self, client, db):
        """transfer_output_files field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, "Output Files", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["transfer_output_files"] == "output.dat, results.tar.gz"

    def test_output_directory_preserved(self, client, db):
        """output_directory field round-trips correctly."""
        tmpl = self._create_and_retrieve(client, "Output Dir", SAMPLE_EXECUTABLE_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["output_directory"] == "osdf:///chtc/staging/u/user/output"

    def test_transfer_output_remaps_preserved(self, client, db):
        """transfer_output_remaps field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, "Output Remaps", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert "transfer_output_remaps" in data
        assert "output.dat" in data["transfer_output_remaps"]
        assert "results.tar.gz" in data["transfer_output_remaps"]

    def test_transfer_input_files_preserved(self, client, db):
        """transfer_input_files field round-trips correctly."""
        tmpl = self._create_and_retrieve(
            client, "Input Files", SAMPLE_EXECUTABLE_SUBMIT
        )
        data = json.loads(tmpl["submit_data"])
        assert data["transfer_input_files"] == "input1.txt, input2.dat"

    def test_executable_and_arguments_preserved(self, client, db):
        """executable and arguments fields round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "Exec", SAMPLE_EXECUTABLE_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["executable"] == "/bin/sleep"
        assert data["arguments"] == "60"

    def test_resource_requests_preserved(self, client, db):
        """request_cpus/memory/disk fields round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "Resources", SAMPLE_EXECUTABLE_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["request_cpus"] == "2"
        assert data["request_memory"] == "2 GB"
        assert data["request_disk"] == "4 GB"

    def test_output_log_paths_preserved(self, client, db):
        """output, error, log paths round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "Paths", SAMPLE_EXECUTABLE_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["output"] == "test.out"
        assert data["error"] == "test.err"
        assert data["log"] == "test.log"

    def test_custom_classads_preserved(self, client, db):
        """Custom ClassAd attributes round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "Custom", SAMPLE_EXECUTABLE_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["MyCustomAttr"] == "custom_value"
        assert data["AnotherAttr"] == "another_value"

    def test_shell_command_preserved(self, client, db):
        """Shell-mode submit data round-trips correctly."""
        tmpl = self._create_and_retrieve(client, "Shell", SAMPLE_SHELL_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["shell"] == "sleep 60"
        assert "executable" not in data

    def test_container_universe_preserved(self, client, db):
        """Container universe + container_image round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "Container", SAMPLE_CONTAINER_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["universe"] == "container"
        assert data["container_image"] == "osdf:///path/to/image.sif"

    def test_gpu_fields_preserved(self, client, db):
        """All GPU/CUDA fields round-trip correctly."""
        tmpl = self._create_and_retrieve(client, "GPU", SAMPLE_GPU_SUBMIT)
        data = json.loads(tmpl["submit_data"])
        assert data["request_gpus"] == "2"
        assert data["gpus_minimum_capability"] == "8.5"
        assert data["gpus_minimum_memory"] == "4 GB"
        assert data["gpus_minimum_runtime"] == "9.1"
        assert data["cuda_version"] == "11.0"

    def test_raw_text_preserved(self, client, db):
        """Raw text submit_data round-trips verbatim."""
        tmpl = self._create_and_retrieve(client, "Raw Text", SAMPLE_RAW_TEXT)
        assert tmpl["submit_data"] == SAMPLE_RAW_TEXT

    def test_full_submit_dict_round_trip(self, client, db):
        """Every key in the submit dict survives save and retrieve."""
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

        tmpl = self._create_and_retrieve(client, "Full Dict", submit_data)
        saved = json.loads(tmpl["submit_data"])

        for key, value in submit_data.items():
            assert saved.get(key) == value, (
                f"Key {key!r}: expected {value!r}, got {saved.get(key)!r}"
            )

    def test_submit_data_is_valid_json(self, client, db):
        """submit_data stored by the API is always valid JSON when dict input given."""
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


# =============================================================================
# Tests: Timestamps and Ordering
# =============================================================================


class TestTemplateTimestamps:
    """Timestamp-related behavior for templates."""

    def test_created_at_set_on_create(self, client, db):
        """created_at is set on template creation."""
        resp = client.post(
            "/api/templates",
            json={"name": "Timed", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        data = resp.get_json()
        assert data["created_at"] is not None
        # Should be a valid ISO datetime
        dt = _datetime_from_iso(data["created_at"])
        assert dt.tzinfo is not None
        # Should be recent (within last 10 seconds)
        now = datetime.now(timezone.utc)
        assert (now - dt).total_seconds() < 10

    def test_updated_at_same_as_created_on_create(self, client, db):
        """updated_at equals created_at on initial creation (within 1 second tolerance)."""
        resp = client.post(
            "/api/templates",
            json={"name": "Same", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        data = resp.get_json()
        created = _datetime_from_iso(data["created_at"])
        updated = _datetime_from_iso(data["updated_at"])
        # Allow up to 1 second difference (timestamps may differ by microseconds)
        diff = abs((updated - created).total_seconds())
        assert diff < 1.0, (
            f"Timestamps differ by {diff}s: created={data['created_at']}, "
            f"updated={data['updated_at']}"
        )

    def test_updated_at_changes_on_update(self, client, db):
        """updated_at changes after a PUT."""
        create_resp = client.post(
            "/api/templates",
            json={"name": "ChangeMe", "submit_data": SAMPLE_EXECUTABLE_SUBMIT},
        )
        tmpl_id = create_resp.get_json()["id"]
        original_updated = create_resp.get_json()["updated_at"]

        update_resp = client.put(
            f"/api/templates/{tmpl_id}",
            json={"name": "Changed"},
        )
        new_updated = update_resp.get_json()["updated_at"]

        assert new_updated != original_updated

    def test_list_ordered_by_updated_at_desc(self, client, db):
        """Templates are listed in descending order of updated_at."""
        # Create templates with delays to ensure distinct timestamps
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

    def test_create_template_with_empty_description(self, client, db):
        """POST with empty description stores None or empty string."""
        resp = client.post(
            "/api/templates",
            json={
                "name": "No Desc",
                "description": "",
                "submit_data": SAMPLE_EXECUTABLE_SUBMIT,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        # description is optional, may be None or empty string
        assert data["description"] in (None, "")


# =============================================================================
# Tests: Update Behavior
# =============================================================================


class TestTemplateUpdateBehavior:
    """Fine-grained update behavior tests."""

    def test_partial_update_name_only(self, client, db):
        """PUT only updating name preserves other fields."""
        original_submit = dict(SAMPLE_EXECUTABLE_SUBMIT)
        create_resp = client.post(
            "/api/templates",
            json={
                "name": "Partial",
                "description": "Original desc",
                "submit_data": original_submit,
            },
        )
        tmpl_id = create_resp.get_json()["id"]

        # Update only the name
        client.put(f"/api/templates/{tmpl_id}", json={"name": "Renamed"})

        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.get_json()["templates"] if t["id"] == tmpl_id)
        assert tmpl["name"] == "Renamed"
        assert tmpl["description"] == "Original desc"
        assert json.loads(tmpl["submit_data"]) == original_submit

    def test_partial_update_submit_data_only(self, client, db):
        """PUT only updating submit_data preserves name and description."""
        create_resp = client.post(
            "/api/templates",
            json={
                "name": "FixName",
                "description": "Fix desc",
                "submit_data": SAMPLE_SHELL_SUBMIT,
            },
        )
        tmpl_id = create_resp.get_json()["id"]

        # Update only submit_data
        new_submit = {"executable": "/bin/ls", "universe": "vanilla"}
        client.put(
            f"/api/templates/{tmpl_id}",
            json={"submit_data": new_submit},
        )

        resp = client.get("/api/templates")
        tmpl = next(t for t in resp.get_json()["templates"] if t["id"] == tmpl_id)
        assert tmpl["name"] == "FixName"
        assert tmpl["description"] == "Fix desc"
        assert json.loads(tmpl["submit_data"]) == new_submit
