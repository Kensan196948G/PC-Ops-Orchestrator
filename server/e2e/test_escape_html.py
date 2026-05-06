"""Smoke tests for the escapeHTML helper introduced for Issue #102.

The helper is added in base.html so every authenticated WebUI page can rely
on it. The actual call-site migration (innerHTML wrappers in tasks.js /
dashboard.js / pc_detail.js) is staged for a follow-up PR.
"""


def test_escape_html_helper_is_globally_available(page_with_login, live_server):
    """escapeHTML must be exposed on window from base.html."""
    p = page_with_login
    is_function = p.evaluate("typeof window.escapeHTML === 'function'")
    assert is_function, "escapeHTML must be exposed as a function on window"


def test_escape_html_neutralizes_xss_payload(page_with_login, live_server):
    """escapeHTML must neutralize the canonical XSS payload."""
    p = page_with_login
    out = p.evaluate("window.escapeHTML('<script>alert(1)</script>')")
    assert "<script>" not in out, f"escapeHTML left unsafe '<script>': {out!r}"
    assert "&lt;script&gt;" in out, f"expected entity-encoded output, got {out!r}"


def test_escape_html_handles_quotes_and_amp(page_with_login, live_server):
    """All five HTML special characters must be replaced."""
    p = page_with_login
    out = p.evaluate("window.escapeHTML('<a href=\"x\" onclick=\\'y\\'>&z')")
    # Order-insensitive check that each special char is encoded.
    assert "&lt;" in out
    assert "&gt;" in out
    assert "&quot;" in out
    assert "&#039;" in out
    assert "&amp;" in out


def test_escape_html_handles_null_and_undefined(page_with_login, live_server):
    """null/undefined must produce empty string (avoid 'null'/'undefined' leaks)."""
    p = page_with_login
    assert p.evaluate("window.escapeHTML(null)") == ""
    assert p.evaluate("window.escapeHTML(undefined)") == ""
    # Non-strings must be coerced via String().
    assert p.evaluate("window.escapeHTML(0)") == "0"
    assert p.evaluate("window.escapeHTML(false)") == "false"
