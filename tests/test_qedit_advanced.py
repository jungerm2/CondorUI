"""Playwright integration tests for the QEdit dialog's advanced mode.

The shared ``openQeditDialog`` helper lives in ``app/static/js/common.js`` and is
used by both the dashboard (bulk edit) and the job details page (single job).
Basic mode offers a curated dropdown of common ClassAd attributes; advanced mode
lets the user type any attribute name, with autocomplete seeded from the job's
live ClassAd.
"""

# A minimal but representative job ClassAd passed into the dialog.
FAKE_CLASSAD = {
    "ClusterId": 42,
    "ProcId": 0,
    "JobStatus": 5,
    "HoldReason": "Job held by user",
    "Requirements": "(Target.HasCHTCStaging == true)",
    "RequestCpus": 1,
}


def _open_dialog(page, advanced_default=False):
    """Invoke the shared qedit dialog directly with a fake job + ClassAd."""
    page.evaluate(
        """(opts) => {
            openQeditDialog(
                [{ clusterId: 42, procId: 0 }],
                { classad: opts.classad, advancedDefault: opts.advancedDefault }
            );
        }""",
        {"classad": FAKE_CLASSAD, "advancedDefault": advanced_default},
    )
    page.wait_for_selector("#qedit-modal")


def _set_advanced(page, enabled):
    """Toggle advanced mode via the hidden checkbox (display:none)."""
    page.evaluate(
        """(enabled) => {
            const el = document.querySelector('#qedit-advanced-toggle');
            el.checked = enabled;
            el.dispatchEvent(new Event('change'));
        }""",
        enabled,
    )


def _stub_qedit_fetch(page):
    """Stub fetch so apply/release calls are recorded instead of hitting the API."""
    page.evaluate(
        """() => {
            window.__qeditCalls = [];
            const orig = window.fetch;
            window.fetch = async (url, options) => {
                const asString = String(url);
                if (asString.includes('/api/qedit')) {
                    window.__qeditCalls.push(JSON.parse(options.body));
                }
                if (asString.includes('/api/qedit') || asString.includes('/release')) {
                    return new Response('{}', {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                return orig(url, options);
            };
        }"""
    )


def test_dialog_defaults_to_basic_mode(page, live_server):
    """Without advanced mode, the curated dropdown is used."""
    page.goto(live_server)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    _open_dialog(page)

    assert page.locator("#qedit-modal .qedit-attr-select").count() == 1
    assert page.locator("#qedit-modal .qedit-attr-input").count() == 0
    assert page.locator("#qedit-advanced-note").is_visible() is False
    assert errors == []


def test_advanced_toggle_switches_to_free_text(page, live_server):
    """Toggling advanced mode swaps the dropdown for a free-text input."""
    page.goto(live_server)
    _open_dialog(page)

    _set_advanced(page, True)

    assert page.locator("#qedit-modal .qedit-attr-input").count() == 1
    assert page.locator("#qedit-modal .qedit-attr-select").count() == 0
    assert page.locator("#qedit-advanced-note").is_visible() is True


def test_advanced_suggestions_include_classad_and_known_attrs(page, live_server):
    """The datalist is seeded from live ClassAd fields plus known attributes."""
    page.goto(live_server)
    _open_dialog(page)
    _set_advanced(page, True)

    values = page.eval_on_selector_all(
        "#qedit-attr-datalist option", "els => els.map(e => e.value)"
    )

    assert "HoldReason" in values  # from the live ClassAd
    assert "Requirements" in values  # from the live ClassAd too
    assert "JobPrio" in values  # from ADVANCED_QEDIT_ATTRS


def test_advanced_shows_current_value_hint(page, live_server):
    """Typing an attribute present in the ClassAd shows its current value."""
    page.goto(live_server)
    _open_dialog(page)
    _set_advanced(page, True)

    page.fill("#qedit-modal .qedit-attr-input", "HoldReason")

    placeholder = page.get_attribute("#qedit-modal .qedit-value-input", "placeholder")
    assert placeholder == "Current: Job held by user"


def test_advanced_default_and_toggle_back(page, live_server):
    """advancedDefault opens in advanced mode, and toggling back restores basic."""
    page.goto(live_server)
    _open_dialog(page, advanced_default=True)

    assert page.locator("#qedit-modal .qedit-attr-input").count() == 1
    assert page.locator("#qedit-advanced-note").is_visible() is True

    _set_advanced(page, False)

    assert page.locator("#qedit-modal .qedit-attr-select").count() == 1
    assert page.locator("#qedit-modal .qedit-attr-input").count() == 0
    assert page.locator("#qedit-advanced-note").is_visible() is False


def test_apply_posts_arbitrary_attribute(page, live_server):
    """In advanced mode, the typed attribute name is posted to /api/qedit."""
    page.goto(live_server)
    _stub_qedit_fetch(page)
    _open_dialog(page)
    _set_advanced(page, True)

    page.fill("#qedit-modal .qedit-attr-input", "JobPrio")
    page.fill("#qedit-modal .qedit-value-input", "10")
    page.click("#qedit-apply-btn")

    page.wait_for_function("window.__qeditCalls.length > 0")
    calls = page.evaluate("window.__qeditCalls")

    assert calls == [{"cluster_id": 42, "proc_id": 0, "attr": "JobPrio", "value": "10"}]
    # Dialog closes after a successful edit (wait for the auto-release step too)
    page.wait_for_selector("#qedit-modal", state="detached")
    assert page.locator("#qedit-modal").count() == 0


def test_apply_rejects_attribute_with_whitespace(page, live_server):
    """Attribute names containing spaces are rejected client-side."""
    page.goto(live_server)
    _stub_qedit_fetch(page)
    _open_dialog(page)
    _set_advanced(page, True)

    page.fill("#qedit-modal .qedit-attr-input", "Bad Attr")
    page.fill("#qedit-modal .qedit-value-input", "1")
    page.click("#qedit-apply-btn")

    assert page.locator(".toast-warning").count() >= 1
    assert page.evaluate("window.__qeditCalls.length") == 0
    # Dialog stays open so the user can correct the name
    assert page.locator("#qedit-modal").count() == 1


def test_enter_in_value_input_applies(page, live_server):
    """Pressing Enter in the value input submits the edit."""
    page.goto(live_server)
    _stub_qedit_fetch(page)
    _open_dialog(page)
    _set_advanced(page, True)

    page.fill("#qedit-modal .qedit-attr-input", "JobPrio")
    page.fill("#qedit-modal .qedit-value-input", "5")
    page.press("#qedit-modal .qedit-value-input", "Enter")

    page.wait_for_function("window.__qeditCalls.length > 0")
    assert page.evaluate("window.__qeditCalls[0].attr") == "JobPrio"


def test_enter_in_attr_input_does_not_apply(page, live_server):
    """Enter in the attribute input must not submit (datalist acceptance)."""
    page.goto(live_server)
    _stub_qedit_fetch(page)
    _open_dialog(page)
    _set_advanced(page, True)

    page.fill("#qedit-modal .qedit-attr-input", "JobPrio")
    page.fill("#qedit-modal .qedit-value-input", "5")
    page.press("#qedit-modal .qedit-attr-input", "Enter")

    # No request should have been made, and the dialog stays open
    assert page.evaluate("window.__qeditCalls.length") == 0
    assert page.locator("#qedit-modal").count() == 1
