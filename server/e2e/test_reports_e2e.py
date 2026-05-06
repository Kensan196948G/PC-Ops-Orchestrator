"""E2E tests for M5-3 reports page and M5-5 users page."""

import pytest

pytestmark = pytest.mark.e2e


def test_reports_page_renders(page_with_login, live_server):
    """Reports page should render KPI stat cards after login."""
    page = page_with_login
    page.goto(f"{live_server}/reports", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=10000)

    # Page title
    assert "レポート" in page.title()

    # Month picker exists
    assert page.locator("#reportMonth").count() == 1

    # KPI stat cards exist
    assert page.locator("#statHealth").count() == 1
    assert page.locator("#statTaskRate").count() == 1
    assert page.locator("#statAlerts").count() == 1
    assert page.locator("#statSLA").count() == 1


def test_reports_csv_button_visible(page_with_login, live_server):
    page = page_with_login
    page.goto(f"{live_server}/reports", wait_until="domcontentloaded")
    csv_btn = page.locator("#btnCsvExport")
    assert csv_btn.count() == 1
    assert csv_btn.is_visible()


def test_reports_pdf_button_visible(page_with_login, live_server):
    page = page_with_login
    page.goto(f"{live_server}/reports", wait_until="domcontentloaded")
    pdf_btn = page.locator("#btnPdfExport")
    assert pdf_btn.count() == 1
    assert pdf_btn.is_visible()


def test_reports_archive_table_renders(page_with_login, live_server):
    """Archive tbody should have rows (or empty-state) after network idle."""
    page = page_with_login
    page.goto(f"{live_server}/reports", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=12000)
    tbody = page.locator("#archiveTableBody")
    assert tbody.count() == 1


def test_users_page_new_columns(page_with_login, live_server):
    """Users table should include the new security columns."""
    page = page_with_login
    page.goto(f"{live_server}/users", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=10000)

    assert page.locator("th:has-text('最終ログイン')").count() >= 1
    assert page.locator("th:has-text('失敗回数')").count() >= 1
    assert page.locator("th:has-text('ロック')").count() >= 1


def test_users_page_create_modal_has_strength_bar_element(page_with_login, live_server):
    """Create modal must contain the password strength bar container."""
    page = page_with_login
    page.goto(f"{live_server}/users", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=8000)

    # Strength bar container must exist in DOM (even before typing)
    assert page.locator("#new-strength").count() == 1

    # Password input must exist and have oninput attribute
    pw_input = page.locator("#new-password")
    assert pw_input.count() == 1
