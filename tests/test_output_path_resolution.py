"""The outputs page resolves the output dir from output_destination OR output_directory.

Templates commonly use ``output_directory`` (a plain submit-side path), while
the API historically only recorded ``output_destination`` — jobs whose
tarballs landed correctly on disk never appeared on the outputs page.
"""

from app.condor import _resolve_output_path


def test_resolve_prefers_output_destination():
    assert (
        _resolve_output_path(
            {"output_destination": "/dest", "output_directory": "/dir"}
        )
        == "/dest"
    )


def test_resolve_output_directory_fallback():
    assert (
        _resolve_output_path({"output_directory": "/outputs/00068271"})
        == "/outputs/00068271"
    )


def test_resolve_missing_is_none():
    assert _resolve_output_path({}) is None
