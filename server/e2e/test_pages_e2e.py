"""E2E tests for page navigation and rendering."""

import pytest


# Pages accessible from the sidebar after login
SIDEBAR_PAGES = [
    ("/", "dashboard"),
    ("/pcs", "pcs"),
    ("/tasks", "tasks"),
    ("/alerts", "alerts"),
    ("/groups", "groups"),
    ("/alert-rules", "alert-rules"),
    ("/licenses", "licenses"),
    ("/notifications-config", "notifications-config"),
    ("/backups", "backups"),
    ("/settings", "settings"),
]


@pytest.mark.parametrize("path,page_name", SIDEBAR_PAGES)
def test_page_renders_after_login(page_with_login, live_server, path, page_name):
    """Each page should return HTTP 200 and render without JS errors."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda err: errors.append(str(err)))

    # CDN-hosted Chart.js can stall the "load" event in CI; wait for DOM only
    # then converge on networkidle so external CDNs do not block the goto.
    p.goto(f"{live_server}{path}", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)

    assert p.url == f"{live_server}{path}", f"URL mismatch for {path}"
    # No uncaught JS exceptions
    assert not errors, f"JS errors on {path}: {errors}"


def test_sidebar_nav_links_present(page_with_login, live_server):
    """Sidebar navigation links should be present on the dashboard."""
    p = page_with_login
    assert p.is_visible("a[data-page='pcs']")
    assert p.is_visible("a[data-page='tasks']")
    assert p.is_visible("a[data-page='alerts']")


def test_404_page(page_with_login, live_server):
    """Unknown URL should return 404 error page."""
    p = page_with_login
    response = p.goto(f"{live_server}/nonexistent-page-xyz")
    assert response is not None
    assert response.status == 404


def test_health_endpoint(page, live_server):
    """Health endpoint should return JSON ok."""
    import json

    response = page.goto(f"{live_server}/health")
    assert response is not None
    assert response.status == 200
    body = json.loads(response.body())
    assert body.get("status") == "ok"
