"""E2E tests for authentication flow."""


def test_login_page_renders(page, live_server):
    page.goto(f"{live_server}/login")
    assert page.title() == "PC-Ops Orchestrator - Login"
    assert page.is_visible("#username")
    assert page.is_visible("#password")
    assert page.is_visible("button[type=submit]")


def test_login_success_redirects_to_dashboard(page, live_server):
    page.goto(f"{live_server}/login")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    # Dashboard page should be visible after login
    assert page.url == f"{live_server}/"


def test_login_invalid_credentials_shows_error(page, live_server):
    page.goto(f"{live_server}/login")
    page.fill("#username", "admin")
    page.fill("#password", "wrongpassword")
    page.click("button[type=submit]")
    # Error box becomes visible with .show class
    page.wait_for_selector("#login-error-box.show", timeout=5000)
    error_text = page.text_content("#login-error-msg")
    assert error_text, "Expected an error message"


def test_login_empty_fields_prevented(page, live_server):
    page.goto(f"{live_server}/login")
    page.click("button[type=submit]")
    # HTML5 required prevents submission; we remain on login page
    assert "/login" in page.url


def test_logout(page_with_login, live_server):
    page = page_with_login
    # Click logout
    page.click("#logout-btn")
    # Should redirect to login
    page.wait_for_url("**/login", timeout=5000)
    assert "/login" in page.url
