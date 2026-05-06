"""UI rendering tests — verify all pages display correctly (items 1-20)."""

import pytest


# All sidebar pages that should render after login
PAGES = [
    ("/", "PC-Ops Orchestrator - Dashboard"),
    ("/pcs", "PC-Ops Orchestrator - PC"),
    ("/tasks", "PC-Ops Orchestrator - タスク"),
    ("/alerts", "PC-Ops Orchestrator - アラート"),
    ("/scheduled-tasks", "PC-Ops Orchestrator - スケジュール"),
    ("/groups", "PC-Ops Orchestrator - PCグループ"),
    ("/alert-rules", "PC-Ops Orchestrator - アラートルール"),
    ("/reports", "PC-Ops Orchestrator - レポート・分析"),
    ("/agents", "PC-Ops Orchestrator - Agent管理"),
    ("/settings", "PC-Ops Orchestrator - システム設定"),
    ("/certs", "PC-Ops Orchestrator - 証明書管理"),
    ("/backups", "PC-Ops Orchestrator - バックアップ管理"),
    ("/notifications-config", "PC-Ops Orchestrator - 通知設定"),
    ("/licenses", "PC-Ops Orchestrator - ライセンス管理"),
]


@pytest.mark.parametrize("path,expected_title_fragment", PAGES)
def test_page_renders_with_sidebar(
    page_with_login, live_server, path, expected_title_fragment
):
    """Each authenticated page should render the sidebar and have a non-empty title."""
    p = page_with_login
    p.goto(f"{live_server}{path}")
    p.wait_for_load_state("domcontentloaded", timeout=10000)
    title = p.title()
    assert title, f"Page title must not be empty for {path}"
    # Sidebar nav must be present
    assert p.locator(".sidebar").count() > 0, f"Sidebar missing on {path}"


def test_login_page_title(page, live_server):
    """Login page must have the correct title."""
    page.goto(f"{live_server}/login")
    assert page.title() == "PC-Ops Orchestrator - Login"


def test_login_page_form_elements(page, live_server):
    """Login form must have username, password inputs and a submit button."""
    page.goto(f"{live_server}/login")
    assert page.locator("#username").count() == 1
    assert page.locator("#password").count() == 1
    assert page.locator("button[type=submit]").count() == 1
    assert page.locator("#login-error-box").count() == 1


def test_login_page_japanese_text(page, live_server):
    """Login page must render Japanese text correctly.

    Note: the brand wordmark is split into two stacked elements
    (`.aside-brand-name` = "PC-Ops", `.aside-brand-sub` = "Orchestrator")
    in the Claude Design 2-column layout, so we cannot assert the
    concatenated string in body text.
    """
    page.goto(f"{live_server}/login")
    body_text = page.text_content("body")
    assert "PC-Ops" in body_text
    assert "Orchestrator" in body_text
    assert "PC運用を、" in body_text


def test_404_page_status_and_content(page, live_server):
    """A request to an unknown URL must return HTTP 404 and show the error code."""
    response = page.goto(f"{live_server}/nonexistent-xyz-page")
    assert response is not None
    assert response.status == 404
    body_text = page.text_content("body")
    assert "404" in body_text


def test_404_page_message(page, live_server):
    """404 error page must display the expected Japanese message."""
    page.goto(f"{live_server}/this-does-not-exist")
    body_text = page.text_content("body")
    assert "ページが見つかりません" in body_text


def test_dashboard_japanese_labels(page_with_login, live_server):
    """Dashboard stat card labels must be in Japanese."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    body_text = p.text_content("body")
    assert "総PC数" in body_text
    assert "正常" in body_text


def test_nav_icon_html_entities_rendered(page_with_login, live_server):
    """Nav icons (HTML entities) must appear in the sidebar."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    icons = p.locator(".nav-icon").all()
    assert len(icons) > 0, "At least one .nav-icon element must exist"
    # Each icon must contain an SVG (not text anymore — SVG icons used)
    for icon in icons:
        assert icon.locator("svg").count() > 0, "nav-icon must contain an SVG element"


def test_dashboard_has_table(page_with_login, live_server):
    """Dashboard page must include at least one <table> element."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator("table").count() > 0, "Dashboard must have at least one table"


def test_toast_container_in_dom(page_with_login, live_server):
    """toast-container must exist in DOM on authenticated pages."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator("#toast-container").count() == 1, (
        "#toast-container must be present"
    )


def test_sidebar_title_text(page_with_login, live_server):
    """Sidebar title must show 'PC-Ops'."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    title_text = p.locator(".brand-name").text_content()
    assert "PC-Ops" in title_text


def test_main_content_area_exists(page_with_login, live_server):
    """The .main-content element must be present on every sidebar page."""
    p = page_with_login
    for path, _ in PAGES:
        p.goto(f"{live_server}{path}")
        p.wait_for_load_state("domcontentloaded", timeout=8000)
        assert p.locator(".main-content").count() > 0, (
            f".main-content missing on {path}"
        )


def test_login_page_no_sidebar(page, live_server):
    """Login page must NOT render the sidebar."""
    page.goto(f"{live_server}/login")
    assert page.locator(".sidebar").count() == 0, (
        "Sidebar must not appear on login page"
    )


def test_static_css_loads(page, live_server):
    """style.css must respond with HTTP 200."""
    response = page.goto(f"{live_server}/static/css/style.css")
    assert response is not None
    assert response.status == 200


def test_pcs_page_renders(page_with_login, live_server):
    """PC list page must contain the table structure."""
    p = page_with_login
    p.goto(f"{live_server}/pcs")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator(".layout").count() > 0


def test_tasks_page_renders(page_with_login, live_server):
    """Tasks page must render the layout without JS errors."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(f"{live_server}/tasks")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"JS errors on /tasks: {errors}"


def test_alerts_page_renders(page_with_login, live_server):
    """Alerts page must render the layout without JS errors."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(f"{live_server}/alerts")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"JS errors on /alerts: {errors}"


# ── Issue #93: Topbar + Sidebar Badge regression tests ──


def test_topbar_renders_on_dashboard(page_with_login, live_server):
    """Dashboard must render the new topbar with search, env-pill, bell, sync, create-task."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator(".topbar").count() == 1
    assert p.locator("#topbar-search").count() == 1
    assert p.locator("#env-pill").count() == 1
    assert p.locator("#topbar-bell").count() == 1
    assert p.locator("#topbar-sync-btn").count() == 1
    assert p.locator("#topbar-create-task").count() == 1


def test_topbar_search_kbd_shortcut_displayed(page_with_login, live_server):
    """⌘K hint must be visible inside the topbar search."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    kbd = p.locator(".topbar .kbd")
    assert kbd.count() >= 1
    assert "K" in (kbd.first.text_content() or "")


def test_sidebar_badges_exist(page_with_login, live_server):
    """Sidebar must contain the muted count badges for PC / Tasks / Agents."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator("#pcs-badge").count() == 1
    assert p.locator("#tasks-badge").count() == 1
    assert p.locator("#agents-badge").count() == 1


def test_main_wrapper_present(page_with_login, live_server):
    """The .main wrapper must exist between sidebar and main-content."""
    p = page_with_login
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=8000)
    assert p.locator(".main > .topbar").count() == 1
    assert p.locator(".main > .main-content").count() == 1
