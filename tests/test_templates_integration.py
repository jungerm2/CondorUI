"""Playwright integration tests for template save/load round-trip.

Tests that saving a template from the Form Builder and then loading it
preserves ALL form fields correctly, including the ones that were
previously missing (transfer_output_files, output_directory,
transfer_output_remaps, GPU fields, etc.).
"""

import time

# =============================================================================
# Canonical list of all form-mapped fields
# =============================================================================
# This must match the standardKeys array in submit.js's checkSelectedTemplate().
# If a new field is added to the form, it must be added here AND in submit.js.
ALL_FORM_FIELDS = {
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


def _get_form_field_value(page, field_id: str) -> str:
    """Get the value of a form input by its id."""
    return page.evaluate(f"document.getElementById('{field_id}')?.value || ''")


def _set_form_field_value(page, field_id: str, value):
    """Set the value of a form input by its id and dispatch an input event."""
    page.evaluate(
        f"""() => {{
        const el = document.getElementById('{field_id}');
        if (!el) return;
        el.value = '{value}';
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}"""
    )


def _get_extra_attrs(page) -> dict:
    """Get the current extra attributes as a dict."""
    return page.evaluate("""() => {
        const rows = document.querySelectorAll('#extra-attrs .attr-row');
        const result = {};
        rows.forEach(row => {
            const key = row.querySelector('.attr-key')?.value?.trim();
            const val = row.querySelector('.attr-value')?.value?.trim();
            if (key) result[key] = val;
        });
        return result;
    }""")


def _add_extra_attr(page, key: str, value: str):
    """Add an extra attribute row via the UI."""
    page.click("#add-attr-btn")
    time.sleep(0.1)
    rows = page.query_selector_all("#extra-attrs .attr-row")
    last_row = rows[-1]
    last_row.query_selector(".attr-key").fill(key)
    last_row.query_selector(".attr-value").fill(value)


def _get_remaps_text(page) -> str:
    """Get the transfer_output_remaps textarea value."""
    return page.evaluate(
        "document.getElementById('job-output-remaps')?.value?.trim() || ''"
    )


def _set_remaps_text(page, text: str):
    """Set the transfer_output_remaps textarea value."""
    page.evaluate(
        f"""() => {{
        const el = document.getElementById('job-output-remaps');
        if (!el) return;
        el.value = `{text}`;
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}"""
    )


class TestTemplateIntegration:
    """End-to-end template save/load round-trip via the browser."""

    def test_save_and_load_template_all_fields(self, live_server, page):
        """Save a template with ALL form fields, then load it and verify every field."""
        # ------------------------------------------------------------------
        # 1. Navigate to the submit page
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")

        # Wait for the form to be ready (files/containers/executables loaded)
        page.wait_for_selector("#job-name", state="visible")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 2. Fill in ALL form fields
        # ------------------------------------------------------------------
        # Job name
        _set_form_field_value(page, "job-name", "Integration Test Template")

        # Universe
        page.select_option("#job-universe", "vanilla")

        # Executable mode (not shell)
        page.click("#execmode-exec-btn")
        time.sleep(0.1)

        # Executable
        _set_form_field_value(page, "job-executable", ALL_FORM_FIELDS["executable"])

        # Arguments
        _set_form_field_value(page, "job-arguments", ALL_FORM_FIELDS["arguments"])

        # Resources
        _set_form_field_value(page, "job-cpus", ALL_FORM_FIELDS["request_cpus"])
        _set_form_field_value(page, "job-memory", ALL_FORM_FIELDS["request_memory"])
        _set_form_field_value(page, "job-disk", ALL_FORM_FIELDS["request_disk"])

        # GPU fields
        _set_form_field_value(page, "job-gpus", ALL_FORM_FIELDS["request_gpus"])
        _set_form_field_value(
            page, "job-gpu-min-capability", ALL_FORM_FIELDS["gpus_minimum_capability"]
        )
        _set_form_field_value(
            page, "job-gpu-min-memory", ALL_FORM_FIELDS["gpus_minimum_memory"]
        )
        _set_form_field_value(
            page, "job-gpu-min-runtime", ALL_FORM_FIELDS["gpus_minimum_runtime"]
        )
        _set_form_field_value(page, "job-cuda-version", ALL_FORM_FIELDS["cuda_version"])

        # Output/log paths
        _set_form_field_value(page, "job-output", ALL_FORM_FIELDS["output"])
        _set_form_field_value(page, "job-error", ALL_FORM_FIELDS["error"])
        _set_form_field_value(page, "job-log", ALL_FORM_FIELDS["log"])

        # Transfer output files
        _set_form_field_value(
            page, "job-transfer-output", ALL_FORM_FIELDS["transfer_output_files"]
        )

        # Output directory
        _set_form_field_value(
            page, "job-output-directory", ALL_FORM_FIELDS["output_directory"]
        )

        # Transfer output remaps (textarea)
        _set_remaps_text(page, ALL_FORM_FIELDS["transfer_output_remaps"])

        # Transfer input files (manual entry, no server files to match)
        _set_form_field_value(
            page, "job-transfer-input", ALL_FORM_FIELDS["transfer_input_files"]
        )

        # Transfer executable checkbox
        page.check("#job-transfer-executable")

        # Extra attributes (non-standard keys)
        _add_extra_attr(page, "should_transfer_files", "YES")
        _add_extra_attr(page, "when_to_transfer_output", "ON_EXIT")
        _add_extra_attr(page, "notification", "Always")
        _add_extra_attr(page, "Requirements", "(Target.HasCHTCStaging == true)")
        _add_extra_attr(page, "MyCustom", "custom_val")
        _add_extra_attr(page, "AnotherCustom", "12345")

        time.sleep(0.2)

        # ------------------------------------------------------------------
        # 3. Save as template
        # ------------------------------------------------------------------
        page.click("#save-as-tmpl-btn")
        time.sleep(0.3)

        # The modal should be visible now
        page.wait_for_selector("#save-template-modal.active", state="visible")
        time.sleep(0.2)

        # The template name should be pre-filled with the job name
        tmpl_name = _get_form_field_value(page, "save-template-name")
        assert tmpl_name == "Integration Test Template", (
            f"Expected template name 'Integration Test Template', got '{tmpl_name}'"
        )

        # Click Save
        page.click("#save-template-confirm-btn")
        time.sleep(0.5)

        # Wait for the toast notification
        page.wait_for_selector(".toast", state="visible", timeout=5000)
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 4. Navigate to templates page
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/templates")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Find the "Use Template" button for our template
        use_btn = page.locator(".use-tmpl-btn").first
        assert use_btn.is_visible(), "Use Template button not found"

        # Click "Use Template" — this stores the template in localStorage
        # and navigates to /submit
        use_btn.click()
        page.wait_for_url(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 5. Verify ALL form fields are restored
        # ------------------------------------------------------------------
        # Job name
        assert _get_form_field_value(page, "job-name") == "Integration Test Template", (
            "Job name not restored"
        )

        # Universe
        assert _get_form_field_value(page, "job-universe") == "vanilla", (
            "Universe not restored"
        )

        # Executable
        assert (
            _get_form_field_value(page, "job-executable")
            == ALL_FORM_FIELDS["executable"]
        ), "Executable not restored"

        # Arguments
        assert (
            _get_form_field_value(page, "job-arguments") == ALL_FORM_FIELDS["arguments"]
        ), "Arguments not restored"

        # Resources
        assert (
            _get_form_field_value(page, "job-cpus") == ALL_FORM_FIELDS["request_cpus"]
        ), "CPUs not restored"
        assert (
            _get_form_field_value(page, "job-memory")
            == ALL_FORM_FIELDS["request_memory"]
        ), "Memory not restored"
        assert (
            _get_form_field_value(page, "job-disk") == ALL_FORM_FIELDS["request_disk"]
        ), "Disk not restored"

        # GPU fields
        assert _get_form_field_value(page, "job-gpus") == str(
            ALL_FORM_FIELDS["request_gpus"]
        ), "GPUs not restored"
        assert (
            _get_form_field_value(page, "job-gpu-min-capability")
            == ALL_FORM_FIELDS["gpus_minimum_capability"]
        ), "GPU min capability not restored"
        assert (
            _get_form_field_value(page, "job-gpu-min-memory")
            == ALL_FORM_FIELDS["gpus_minimum_memory"]
        ), "GPU min memory not restored"
        assert (
            _get_form_field_value(page, "job-gpu-min-runtime")
            == ALL_FORM_FIELDS["gpus_minimum_runtime"]
        ), "GPU min runtime not restored"
        assert (
            _get_form_field_value(page, "job-cuda-version")
            == ALL_FORM_FIELDS["cuda_version"]
        ), "CUDA version not restored"

        # Output/log paths
        assert _get_form_field_value(page, "job-output") == ALL_FORM_FIELDS["output"], (
            "Output not restored"
        )
        assert _get_form_field_value(page, "job-error") == ALL_FORM_FIELDS["error"], (
            "Error not restored"
        )
        assert _get_form_field_value(page, "job-log") == ALL_FORM_FIELDS["log"], (
            "Log not restored"
        )

        # Transfer output files
        assert (
            _get_form_field_value(page, "job-transfer-output")
            == ALL_FORM_FIELDS["transfer_output_files"]
        ), "Transfer output files not restored"

        # Output directory
        assert (
            _get_form_field_value(page, "job-output-directory")
            == ALL_FORM_FIELDS["output_directory"]
        ), "Output directory not restored"

        # Transfer output remaps
        remaps = _get_remaps_text(page)
        assert "result.dat" in remaps, (
            f"Transfer output remaps not restored: got '{remaps}'"
        )

        # Transfer input files
        transfer_input = _get_form_field_value(page, "job-transfer-input")
        assert "a.dat" in transfer_input, (
            f"Transfer input files not restored: got '{transfer_input}'"
        )

        # Transfer executable checkbox
        is_checked = page.evaluate(
            "document.getElementById('job-transfer-executable')?.checked || false"
        )
        assert is_checked, "Transfer executable checkbox not checked"

        # Extra attributes
        extra_attrs = _get_extra_attrs(page)
        assert extra_attrs.get("should_transfer_files") == "YES", (
            f"should_transfer_files not restored: {extra_attrs}"
        )
        assert extra_attrs.get("when_to_transfer_output") == "ON_EXIT", (
            f"when_to_transfer_output not restored: {extra_attrs}"
        )
        assert extra_attrs.get("notification") == "Always", (
            f"notification not restored: {extra_attrs}"
        )
        assert extra_attrs.get("Requirements") == "(Target.HasCHTCStaging == true)", (
            f"Requirements not restored: {extra_attrs}"
        )
        assert extra_attrs.get("MyCustom") == "custom_val", (
            f"MyCustom not restored: {extra_attrs}"
        )
        assert extra_attrs.get("AnotherCustom") == "12345", (
            f"AnotherCustom not restored: {extra_attrs}"
        )

    def test_save_and_load_raw_template(self, live_server, page, app):
        """Save a raw text template and verify it loads correctly."""
        # ------------------------------------------------------------------
        # 1. Navigate to submit page and switch to Raw Editor
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#job-name", state="visible")
        time.sleep(0.3)

        page.click("#mode-raw-btn")
        time.sleep(0.3)

        # Fill in raw editor
        raw_text = """universe = vanilla
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
output_directory = osdf:///chtc/staging/u/user/output
transfer_output_remaps = output.dat = osdf:///chtc/staging/u/user/output.dat; results.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz
request_gpus = 2
gpus_minimum_capability = 8.5
gpus_minimum_memory = 4 GB
gpus_minimum_runtime = 9.1
cuda_version = 11.0
MyCustomAttr = custom_value
AnotherAttr = another_value

queue 1"""

        page.fill("#raw-submit-editor", raw_text)
        _set_form_field_value(page, "raw-job-name", "Raw Integration Test")
        time.sleep(0.2)

        # ------------------------------------------------------------------
        # 2. Save as template from raw mode
        # ------------------------------------------------------------------
        page.click("#raw-save-as-tmpl-btn")
        time.sleep(0.3)
        page.wait_for_selector("#save-template-modal.active", state="visible")
        time.sleep(0.2)

        # Verify pre-filled name
        tmpl_name = _get_form_field_value(page, "save-template-name")
        assert tmpl_name == "Raw Integration Test", (
            f"Expected 'Raw Integration Test', got '{tmpl_name}'"
        )

        page.click("#save-template-confirm-btn")
        time.sleep(0.5)
        page.wait_for_selector(".toast", state="visible", timeout=5000)
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 3. Load the template
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/templates")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Find the "Use Template" button for our raw template
        use_btn = page.locator(".use-tmpl-btn").first
        assert use_btn.is_visible(), "Use Template button not found"
        use_btn.click()

        page.wait_for_url(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 4. Verify raw text is restored
        # ------------------------------------------------------------------
        # Since the raw text starts with "universe" (not "{"), it should
        # switch to Raw Editor mode and fill the textarea
        restored_text = page.evaluate(
            "document.getElementById('raw-submit-editor')?.value || ''"
        )
        assert "executable = /bin/sleep" in restored_text, (
            f"Raw text not restored properly: {restored_text[:200]}..."
        )
        assert "transfer_output_files" in restored_text, (
            "transfer_output_files missing from restored raw text"
        )
        assert "output_directory" in restored_text, (
            "output_directory missing from restored raw text"
        )
        assert "request_gpus" in restored_text, (
            "request_gpus missing from restored raw text"
        )
        assert "gpus_minimum_capability" in restored_text, (
            "gpus_minimum_capability missing from restored raw text"
        )

    def test_save_and_load_form_template_variable_queue(self, live_server, page):
        """Save a Form Builder template with a non-integer queue variable and verify it loads."""
        # ------------------------------------------------------------------
        # 1. Navigate to the submit page
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#job-name", state="visible")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 2. Fill in form fields with a non-default queue count
        # ------------------------------------------------------------------
        # Job name
        _set_form_field_value(page, "job-name", "Form Queue Variable")

        # Universe
        page.select_option("#job-universe", "vanilla")

        # Executable mode (not shell)
        page.click("#execmode-exec-btn")
        time.sleep(0.1)

        # Executable
        _set_form_field_value(page, "job-executable", "/bin/sleep")

        # Arguments
        _set_form_field_value(page, "job-arguments", "60")

        # Resources
        _set_form_field_value(page, "job-cpus", "1")
        _set_form_field_value(page, "job-memory", "1 GB")
        _set_form_field_value(page, "job-disk", "1 GB")

        # Set queue to a variable expression (non-integer)
        _set_form_field_value(page, "job-count", "$(N)")

        time.sleep(0.2)

        # ------------------------------------------------------------------
        # 3. Save as template
        # ------------------------------------------------------------------
        page.click("#save-as-tmpl-btn")
        time.sleep(0.3)
        page.wait_for_selector("#save-template-modal.active", state="visible")
        time.sleep(0.2)

        # Verify pre-filled name
        tmpl_name = _get_form_field_value(page, "save-template-name")
        assert tmpl_name == "Form Queue Variable", (
            f"Expected 'Form Queue Variable', got '{tmpl_name}'"
        )

        page.click("#save-template-confirm-btn")
        time.sleep(0.5)
        page.wait_for_selector(".toast", state="visible", timeout=5000)
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 4. Navigate to templates page and load the template
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/templates")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        use_btn = page.locator(".use-tmpl-btn").first
        assert use_btn.is_visible(), "Use Template button not found"
        use_btn.click()

        page.wait_for_url(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 5. Verify queue value is preserved as the variable expression
        # ------------------------------------------------------------------
        queue_value = _get_form_field_value(page, "job-count")
        assert queue_value == "$(N)", (
            f"Queue variable not preserved: expected '$(N)', got '{queue_value}'"
        )

        # Also verify other form fields are intact
        assert _get_form_field_value(page, "job-executable") == "/bin/sleep", (
            "Executable not preserved"
        )
        assert _get_form_field_value(page, "job-arguments") == "60", (
            "Arguments not preserved"
        )

    def test_save_and_load_raw_template_variable_queue(self, live_server, page):
        """Save a raw text template with a non-integer queue variable and verify it loads."""
        # ------------------------------------------------------------------
        # 1. Navigate to submit page and switch to Raw Editor
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#job-name", state="visible")
        time.sleep(0.3)

        page.click("#mode-raw-btn")
        time.sleep(0.3)

        # Fill in raw editor with a variable queue expression
        raw_text = """universe = vanilla
executable = /bin/sleep
arguments = 60
request_cpus = 2
request_memory = 2 GB
request_disk = 4 GB
output = test.out
error = test.err
log = test.log

queue $(N)"""

        page.fill("#raw-submit-editor", raw_text)
        _set_form_field_value(page, "raw-job-name", "Variable Queue Raw")
        time.sleep(0.2)

        # ------------------------------------------------------------------
        # 2. Save as template from raw mode
        # ------------------------------------------------------------------
        page.click("#raw-save-as-tmpl-btn")
        time.sleep(0.3)
        page.wait_for_selector("#save-template-modal.active", state="visible")
        time.sleep(0.2)

        # Verify pre-filled name
        tmpl_name = _get_form_field_value(page, "save-template-name")
        assert tmpl_name == "Variable Queue Raw", (
            f"Expected 'Variable Queue Raw', got '{tmpl_name}'"
        )

        page.click("#save-template-confirm-btn")
        time.sleep(0.5)
        page.wait_for_selector(".toast", state="visible", timeout=5000)
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 3. Load the template
        # ------------------------------------------------------------------
        page.goto(f"{live_server}/templates")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Find the "Use Template" button for our raw template
        # (It should be the first one since it was most recently updated)
        use_btn = page.locator(".use-tmpl-btn").first
        assert use_btn.is_visible(), "Use Template button not found"
        use_btn.click()

        page.wait_for_url(f"{live_server}/submit")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # ------------------------------------------------------------------
        # 4. Verify raw text is restored with the variable queue preserved
        # ------------------------------------------------------------------
        restored_text = page.evaluate(
            "document.getElementById('raw-submit-editor')?.value || ''"
        )
        assert "queue $(N)" in restored_text, (
            f"Variable queue not preserved in restored text: {restored_text[:200]}..."
        )
        assert "executable = /bin/sleep" in restored_text, (
            f"Raw text not restored properly: {restored_text[:200]}..."
        )
