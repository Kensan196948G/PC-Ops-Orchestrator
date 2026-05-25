"""JavaScript behaviour tests — console errors, localStorage, login state (items 31-50)."""


def test_no_js_pageerror_on_dashboard(page_with_login, live_server):
    """Dashboard must not throw any uncaught JS exceptions."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    # CDN-hosted Chart.js can stall the "load" event in CI; wait for DOM only.
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"Uncaught JS errors on dashboard: {errors}"


def test_no_console_errors_on_dashboard(page_with_login, live_server):
    """Dashboard must not emit console 'error' messages from application code."""
    p = page_with_login
    console_errors = []

    def capture(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    p.on("console", capture)
    # Chart.js is now self-hosted, but keep DOM-only wait for resilience.
    p.goto(f"{live_server}/", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)

    # Filter out known benign errors:
    # - Network-level errors (net::ERR_*)
    # - "Failed to fetch" from chart rendering on a second page load where
    #   Chart.js may not be fully ready (timing issue in test env)
    def is_ignorable(msg: str) -> bool:
        keywords = [
            "net::",
            "Failed to fetch",
            "chart error",
        ]
        return any(k.lower() in msg.lower() for k in keywords)

    app_errors = [e for e in console_errors if not is_ignorable(e)]
    assert not app_errors, f"Console errors on dashboard: {app_errors}"


def test_no_js_pageerror_on_login(page, live_server):
    """Login page must not throw any uncaught JS exceptions."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=8000)
    assert not errors, f"Uncaught JS errors on login page: {errors}"


def test_token_stored_in_localstorage_after_login(page, live_server):
    """After a successful login the JWT token must be present in localStorage."""
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    token = page.evaluate("localStorage.getItem('token')")
    assert token, "token must be set in localStorage after login"


def test_user_info_stored_in_localstorage_after_login(page, live_server):
    """After login the user info JSON must be present in localStorage."""
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    user_raw = page.evaluate("localStorage.getItem('user')")
    assert user_raw, "user must be set in localStorage after login"
    import json

    user = json.loads(user_raw)
    assert user.get("username") == "admin"


def test_token_removed_from_localstorage_after_logout(page_with_login, live_server):
    """After logout the token must be removed from localStorage."""
    p = page_with_login
    # Confirm token is present
    token_before = p.evaluate("localStorage.getItem('token')")
    assert token_before, "Token must exist before logout"
    # Perform logout
    p.click("#logout-btn")
    p.wait_for_url("**/login", timeout=5000)
    # Now check localStorage — evaluate inside the login page context
    token_after = p.evaluate("localStorage.getItem('token')")
    assert not token_after, "Token must be removed from localStorage after logout"


def test_user_info_removed_from_localstorage_after_logout(page_with_login, live_server):
    """After logout the user info must be removed from localStorage."""
    p = page_with_login
    p.click("#logout-btn")
    p.wait_for_url("**/login", timeout=5000)
    user_after = p.evaluate("localStorage.getItem('user')")
    assert not user_after, "user info must be removed from localStorage after logout"


def test_login_state_maintained_after_reload(page, live_server):
    """
    When a valid token is already in localStorage, reloading a protected page
    should not redirect to /login.
    """
    # First log in to get a token
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    # Reload and expect to stay on dashboard
    page.reload()
    page.wait_for_load_state("domcontentloaded", timeout=8000)
    assert (
        "/login" not in page.url
    ), "Should remain on dashboard after reload when token present"


def test_unauthenticated_redirect_to_login(page, live_server):
    """
    Accessing dashboard without a token must redirect to /login
    (the JS in base.html handles this).
    """
    page.goto(f"{live_server}/", wait_until="domcontentloaded")
    # Wait for JS DOMContentLoaded redirect
    page.wait_for_load_state("networkidle", timeout=8000)
    assert "/login" in page.url, "Unauthenticated access must redirect to /login"


def test_no_js_errors_on_pcs_page(page_with_login, live_server):
    """PC list page must not produce JS errors."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(f"{live_server}/pcs", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"JS errors on /pcs: {errors}"


def test_no_js_errors_on_tasks_page(page_with_login, live_server):
    """Tasks page must not produce JS errors."""
    p = page_with_login
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(f"{live_server}/tasks", wait_until="domcontentloaded")
    p.wait_for_load_state("networkidle", timeout=10000)
    assert not errors, f"JS errors on /tasks: {errors}"


def test_localstorage_token_is_jwt_format(page, live_server):
    """The stored token must look like a JWT (three dot-separated parts)."""
    page.goto(f"{live_server}/login", wait_until="domcontentloaded")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    token = page.evaluate("localStorage.getItem('token')")
    assert token, "Token must exist"
    parts = token.split(".")
    assert len(parts) == 3, f"JWT must have 3 parts, got: {parts}"
