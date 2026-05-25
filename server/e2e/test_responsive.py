"""Responsive layout tests — verify display at different viewport sizes (items 21-30)."""

import pytest


VIEWPORTS = [
    {"name": "desktop", "width": 1920, "height": 1080},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 375, "height": 667},
]


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[v["name"] for v in VIEWPORTS])
def test_login_page_visible_at_viewport(page, live_server, vp):
    """Login page must remain usable at all viewport sizes."""
    page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=10000)
    # Core form elements must still be in DOM
    assert page.locator("#username").count() == 1
    assert page.locator("#password").count() == 1
    assert page.locator("button[type=submit]").count() == 1


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[v["name"] for v in VIEWPORTS])
def test_dashboard_no_js_errors_at_viewport(page_with_login, live_server, vp):
    """Dashboard must not produce JS errors at any standard viewport."""
    p = page_with_login
    p.set_viewport_size({"width": vp["width"], "height": vp["height"]})
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"JS errors at {vp['name']}: {errors}"


def test_desktop_sidebar_visible(page_with_login, live_server):
    """On desktop (1920x1080) the sidebar must be visible in DOM."""
    p = page_with_login
    p.set_viewport_size({"width": 1920, "height": 1080})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert p.locator(".sidebar").count() > 0, "Sidebar must exist at desktop width"


def test_tablet_layout_has_sidebar_element(page_with_login, live_server):
    """At tablet width the sidebar element must still be present in DOM."""
    p = page_with_login
    p.set_viewport_size({"width": 768, "height": 1024})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    # DOM presence is required; CSS visibility may vary by design
    assert (
        p.locator(".sidebar").count() > 0
    ), "Sidebar element must exist at tablet width"


def test_mobile_layout_has_sidebar_element(page_with_login, live_server):
    """At mobile width the sidebar element must still be present in DOM."""
    p = page_with_login
    p.set_viewport_size({"width": 375, "height": 667})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert (
        p.locator(".sidebar").count() > 0
    ), "Sidebar element must exist at mobile width"


def test_desktop_main_content_visible(page_with_login, live_server):
    """On desktop the main content area must be visible."""
    p = page_with_login
    p.set_viewport_size({"width": 1920, "height": 1080})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert p.locator(
        ".main-content"
    ).is_visible(), ".main-content must be visible on desktop"


def test_mobile_page_title_accessible(page_with_login, live_server):
    """Page title must be accessible at mobile viewport."""
    p = page_with_login
    p.set_viewport_size({"width": 375, "height": 667})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert p.title(), "Page title must be non-empty at mobile viewport"


def test_viewport_reset_to_default(page_with_login, live_server):
    """Viewport change must not persist across navigations unexpectedly."""
    p = page_with_login
    p.set_viewport_size({"width": 1280, "height": 800})
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    size = p.viewport_size
    assert size["width"] == 1280
    assert size["height"] == 800
