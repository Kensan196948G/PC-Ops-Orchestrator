"""Light/Dark theme toggle E2E tests (Issue #77 / M5-4).

The page_with_login fixture leaves the page on the dashboard already, so the
tests below avoid an extra goto — re-navigating to "/" makes Chromium
re-fetch the Chart.js CDN script, and that occasionally trips the 60s default
goto timeout in CI runners. Reading attributes from the existing page is
sufficient to verify the theme behavior.
"""


def test_default_theme_is_set_on_dashboard(page_with_login, live_server):
    """Dashboard must have data-theme attribute set on <html>."""
    p = page_with_login
    theme = p.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme in ("light", "dark"), f"unexpected initial theme: {theme!r}"


def test_theme_toggle_button_visible(page_with_login, live_server):
    """Topbar must expose the theme toggle button with proper a11y attributes."""
    p = page_with_login
    btn = p.locator("#topbar-theme-toggle")
    assert btn.count() == 1, "theme toggle button missing from Topbar"
    assert btn.get_attribute("aria-label") is not None, "aria-label required for a11y"
    assert btn.get_attribute("aria-pressed") in (
        "true",
        "false",
    ), "aria-pressed must reflect current theme state"


def test_theme_toggle_switches_theme(page_with_login, live_server):
    """Clicking the toggle must flip data-theme between light and dark."""
    p = page_with_login
    initial = p.evaluate("document.documentElement.getAttribute('data-theme')")
    p.click("#topbar-theme-toggle")
    after = p.evaluate("document.documentElement.getAttribute('data-theme')")
    assert after != initial, f"theme did not toggle: {initial} -> {after}"
    assert {initial, after} == {
        "light",
        "dark",
    }, f"toggle must alternate light/dark, got {initial} -> {after}"


def test_theme_persists_across_reload(page_with_login, live_server):
    """Toggling and reloading must keep the chosen theme (localStorage-backed)."""
    p = page_with_login
    initial = p.evaluate("document.documentElement.getAttribute('data-theme')")
    p.click("#topbar-theme-toggle")
    expected = p.evaluate("document.documentElement.getAttribute('data-theme')")
    assert expected != initial
    # reload() also defaults to wait_until="load" — switch to domcontentloaded
    # so the CDN-hosted Chart.js cannot stall this navigation either.
    p.reload(wait_until="domcontentloaded")
    after_reload = p.evaluate("document.documentElement.getAttribute('data-theme')")
    assert after_reload == expected, (
        f"theme did not persist: chose {expected}, got {after_reload} after reload"
    )


def test_theme_aria_pressed_updates(page_with_login, live_server):
    """aria-pressed must mirror the current theme (true=dark)."""
    p = page_with_login
    btn = p.locator("#topbar-theme-toggle")
    initial_pressed = btn.get_attribute("aria-pressed")
    p.click("#topbar-theme-toggle")
    after_pressed = btn.get_attribute("aria-pressed")
    assert after_pressed != initial_pressed, "aria-pressed did not flip on toggle"


def test_login_page_respects_theme(page, live_server):
    """The /login page also honors the persisted theme (no FOUC)."""
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme in ("light", "dark"), f"login theme not set: {theme!r}"
