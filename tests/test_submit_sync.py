"""Tests for the bidirectional sync between the submit form and raw editor.

These tests use Playwright to launch a real browser, navigate to the submit
page, and interact with the form and raw editor just like a real user would.
"""

import textwrap

# =============================================================================
# Helpers
# =============================================================================


def fill_form(page, fields: dict):
    """Fill multiple form fields at once.

    Args:
        page: Playwright page object.
        fields: Dict mapping element IDs to values.
    """
    for element_id, value in fields.items():
        page.fill(f"#{element_id}", value)


def get_raw_editor_text(page) -> str:
    """Get the current content of the raw submit editor."""
    return page.input_value("#raw-submit-editor")


def set_raw_editor_text(page, text: str):
    """Set the content of the raw submit editor."""
    page.fill("#raw-submit-editor", text)


def switch_to_raw_mode(page):
    """Click the 'Raw Editor' button to switch modes and trigger syncFormToRaw()."""
    page.click("#mode-raw-btn")
    page.wait_for_selector("#mode-raw.submit-mode.active")


def switch_to_form_mode(page):
    """Click the 'Form Builder' button to switch modes and trigger syncRawToForm()."""
    page.click("#mode-form-btn")
    page.wait_for_selector("#mode-form.submit-mode.active")


# =============================================================================
# Tests: Form → Raw Editor (syncFormToRaw)
# =============================================================================


class TestFormToRawSync:
    """Tests for syncFormToRaw() — Form Builder → Raw Editor."""

    def test_transfer_output_files(self, page, live_server):
        """Set transfer_output_files and verify it appears in raw editor."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-transfer-output": "output.dat, results.tar.gz",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "transfer_output_files = output.dat, results.tar.gz" in raw

    def test_output_destination(self, page, live_server):
        """Set output_destination and verify it appears in raw editor."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-output-destination": "osdf:///chtc/staging/u/user/output",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "output_destination = osdf:///chtc/staging/u/user/output" in raw

    def test_output_remaps(self, page, live_server):
        """Set output remaps and verify they appear in raw editor."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
            },
        )

        # Fill the remaps textarea
        page.fill(
            "#job-output-remaps",
            "output.dat = osdf:///chtc/staging/u/user/output.dat\nresults.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz",
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert (
            "transfer_output_remaps = output.dat = osdf:///chtc/staging/u/user/output.dat; results.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz"
            in raw
        )

    def test_basic_executable_submission(self, page, live_server):
        """Fill in a basic executable submission and verify the raw editor output."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-arguments": "60",
                "job-cpus": "2",
                "job-memory": "2 GB",
                "job-disk": "4 GB",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "universe = vanilla" in raw
        assert "executable = /bin/sleep" in raw
        assert "arguments = 60" in raw
        assert "request_cpus = 2" in raw
        assert "request_memory = 2 GB" in raw
        assert "request_disk = 4 GB" in raw
        assert "queue 1" in raw

    def test_shell_command_submission(self, page, live_server):
        """Set shell mode and verify the raw editor uses 'shell ='."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        page.click("#execmode-shell-btn")
        fill_form(
            page,
            {
                "job-shell-cmd": "sleep 60",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "shell = sleep 60" in raw
        # Executable should NOT appear
        assert "executable =" not in raw

    def test_container_universe(self, page, live_server):
        """Set universe to container and verify container_image appears."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        page.select_option("#job-universe", "container")
        fill_form(
            page,
            {
                "job-container-image": "osdf:///path/to/image.sif",
                "job-executable": "/bin/sleep",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "universe = container" in raw
        assert "container_image = osdf:///path/to/image.sif" in raw

    def test_transfer_input_files(self, page, live_server):
        """Set transfer_input_files and verify it appears in raw editor."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-transfer-input": "file1.txt, file2.txt",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "transfer_input_files = file1.txt, file2.txt" in raw

    def test_additional_classads(self, page, live_server):
        """Add extra attribute rows and verify they appear in raw editor."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
            },
        )

        # Add an extra attribute
        page.click("#add-attr-btn")
        attr_rows = page.locator(".attr-row")
        attr_rows.last.locator(".attr-key").fill("MyCustomAttr")
        attr_rows.last.locator(".attr-value").fill("custom_value")

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "# Additional ClassAds" in raw
        assert "MyCustomAttr = custom_value" in raw

    def test_empty_fields_use_defaults(self, page, live_server):
        """Leave fields empty and verify defaults are used."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "request_cpus = 1" in raw
        assert "request_memory = 1 GB" in raw
        assert "request_disk = 1 GB" in raw
        assert "queue 1" in raw

    def test_job_count(self, page, live_server):
        """Set job count and verify 'queue N' at the end."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-count": "5",
            },
        )

        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert raw.strip().endswith("queue 5")


# =============================================================================
# Tests: Raw Editor → Form (syncRawToForm)
# =============================================================================


class TestRawToFormSync:
    """Tests for syncRawToForm() — Raw Editor → Form Builder."""

    def test_transfer_output_files_parsing(self, page, live_server):
        """Write a submit file with transfer_output_files and verify form field."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            transfer_output_files = output.dat, results.tar.gz
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-transfer-output") == "output.dat, results.tar.gz"

    def test_output_destination_parsing(self, page, live_server):
        """Write a submit file with output_destination and verify form field."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            output_destination = osdf:///chtc/staging/u/user/output
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert (
            page.input_value("#job-output-destination")
            == "osdf:///chtc/staging/u/user/output"
        )

    def test_output_remaps_parsing(self, page, live_server):
        """Write a submit file with transfer_output_remaps and verify textarea."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            transfer_output_remaps = output.dat = osdf:///chtc/staging/u/user/output.dat; results.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        remaps = page.input_value("#job-output-remaps")
        assert "output.dat = osdf:///chtc/staging/u/user/output.dat" in remaps
        assert "results.tar.gz = osdf:///chtc/staging/u/user/results.tar.gz" in remaps

    def test_basic_parsing(self, page, live_server):
        """Write a valid submit file and verify form fields are populated."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            arguments = 60
            request_cpus = 2
            request_memory = 4 GB
            request_disk = 8 GB
            output = my_output.out
            error = my_error.err
            log = my_log.log
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-executable") == "/bin/sleep"
        assert page.input_value("#job-arguments") == "60"
        assert page.input_value("#job-cpus") == "2"
        assert page.input_value("#job-memory") == "4 GB"
        assert page.input_value("#job-disk") == "8 GB"
        assert page.input_value("#job-output") == "my_output.out"
        assert page.input_value("#job-error") == "my_error.err"
        assert page.input_value("#job-log") == "my_log.log"
        assert page.input_value("#job-count") == "1"

    def test_shell_command_parsing(self, page, live_server):
        """Write a submit file with 'shell =' and verify shell mode is activated."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            shell = sleep 60
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-shell-cmd") == "sleep 60"
        assert page.locator("#shell-field").is_visible()
        assert page.locator("#exec-field").is_hidden()

    def test_container_universe_parsing(self, page, live_server):
        """Write a submit file with container_image and verify universe is set."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = container
            container_image = osdf:///path/to/image.sif
            executable = /bin/sleep
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-universe") == "container"
        assert page.input_value("#job-container-image") == "osdf:///path/to/image.sif"

    def test_custom_classads(self, page, live_server):
        """Write a submit file with custom attributes and verify extra attr rows."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            MyCustomAttr = custom_value
            AnotherAttr = another_value
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        attr_rows = page.locator(".attr-row")
        assert attr_rows.count() >= 2

        # Use evaluate to get all input values (Playwright 0.8.0 compat)
        key_texts = page.evaluate("""
            () => Array.from(document.querySelectorAll('.attr-row .attr-key'))
                .map(el => el.value)
        """)
        val_texts = page.evaluate("""
            () => Array.from(document.querySelectorAll('.attr-row .attr-value'))
                .map(el => el.value)
        """)

        assert "MyCustomAttr" in key_texts
        assert "AnotherAttr" in key_texts
        assert "custom_value" in val_texts
        assert "another_value" in val_texts

    def test_comments_are_ignored(self, page, live_server):
        """Write a submit file with comments and verify they don't create form fields."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            # This is a comment
            universe = vanilla
            # Another comment
            executable = /bin/sleep
            # request_cpus = 99  (commented out)
            request_cpus = 2
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-cpus") == "2"
        assert page.input_value("#job-executable") == "/bin/sleep"

    def test_queue_directive_is_parsed(self, page, live_server):
        """Write a submit file with 'queue 5' and verify job count is updated."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            request_cpus = 1
            queue 5
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        # Queue is now parsed from raw -> form
        assert page.input_value("#job-count") == "5"

    def test_transfer_input_files_parsing(self, page, live_server):
        """Write a submit file with transfer_input_files and verify form field."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        submit_content = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            transfer_input_files = file1.txt, file2.txt
            request_cpus = 1
            queue 1
        """)
        set_raw_editor_text(page, submit_content)
        switch_to_form_mode(page)

        assert page.input_value("#job-transfer-input") == "file1.txt, file2.txt"


# =============================================================================
# Tests: Round-trip consistency
# =============================================================================


class TestRoundTripSync:
    """Tests for round-trip consistency between form and raw editor."""

    def test_form_to_raw_to_form_consistency(self, page, live_server):
        """Fill form -> sync to raw -> sync back to form; verify values preserved."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-arguments": "60",
                "job-cpus": "2",
                "job-memory": "2 GB",
                "job-disk": "4 GB",
                "job-output": "test.out",
                "job-error": "test.err",
                "job-log": "test.log",
                "job-count": "3",
            },
        )

        # Sync to raw
        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "executable = /bin/sleep" in raw
        assert "arguments = 60" in raw
        assert "request_cpus = 2" in raw
        assert "request_memory = 2 GB" in raw
        assert "request_disk = 4 GB" in raw
        assert "queue 3" in raw

        # Sync back to form
        switch_to_form_mode(page)

        assert page.input_value("#job-executable") == "/bin/sleep"
        assert page.input_value("#job-arguments") == "60"
        assert page.input_value("#job-cpus") == "2"
        assert page.input_value("#job-memory") == "2 GB"
        assert page.input_value("#job-disk") == "4 GB"
        assert page.input_value("#job-output") == "test.out"
        assert page.input_value("#job-error") == "test.err"
        assert page.input_value("#job-log") == "test.log"
        assert page.input_value("#job-count") == "3"

    def test_output_file_sync_consistency(self, page, live_server):
        """Fill form with output file transfer fields and verify round-trip."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        fill_form(
            page,
            {
                "job-executable": "/bin/sleep",
                "job-transfer-output": "output.dat, results.tar.gz",
                "job-output-destination": "osdf:///chtc/staging/u/user/output",
            },
        )

        # Fill remaps textarea separately
        page.fill(
            "#job-output-remaps", "output.dat = osdf:///chtc/staging/u/user/output.dat"
        )

        # Sync to raw
        switch_to_raw_mode(page)
        raw = get_raw_editor_text(page)

        assert "transfer_output_files = output.dat, results.tar.gz" in raw
        assert "output_destination = osdf:///chtc/staging/u/user/output" in raw
        assert (
            "transfer_output_remaps = output.dat = osdf:///chtc/staging/u/user/output.dat"
            in raw
        )

        # Sync back to form
        switch_to_form_mode(page)

        assert page.input_value("#job-transfer-output") == "output.dat, results.tar.gz"
        assert (
            page.input_value("#job-output-destination")
            == "osdf:///chtc/staging/u/user/output"
        )
        remaps = page.input_value("#job-output-remaps")
        assert "output.dat = osdf:///chtc/staging/u/user/output.dat" in remaps

    def test_raw_to_form_to_raw_consistency(self, page, live_server):
        """Set raw editor -> sync to form -> sync back to raw; verify values preserved."""
        page.goto(f"{live_server}/submit")
        page.wait_for_selector("#mode-form.submit-mode.active")

        switch_to_raw_mode(page)

        original_raw = textwrap.dedent("""\
            universe = vanilla
            executable = /bin/sleep
            arguments = 60
            request_cpus = 2
            request_memory = 2 GB
            request_disk = 4 GB
            output = test.out
            error = test.err
            log = test.log

            queue 3
        """)
        set_raw_editor_text(page, original_raw)

        # Sync to form
        switch_to_form_mode(page)

        assert page.input_value("#job-executable") == "/bin/sleep"
        assert page.input_value("#job-arguments") == "60"
        assert page.input_value("#job-cpus") == "2"
        # Queue is now parsed from raw -> form
        assert page.input_value("#job-count") == "3"

        # Sync back to raw
        switch_to_raw_mode(page)
        final_raw = get_raw_editor_text(page)

        # The round-trip should preserve the key values
        assert "executable = /bin/sleep" in final_raw
        assert "arguments = 60" in final_raw
        assert "request_cpus = 2" in final_raw
        assert "request_memory = 2 GB" in final_raw
        assert "request_disk = 4 GB" in final_raw
        # Queue is now parsed from raw -> form, so it preserves the value
        assert "queue 3" in final_raw