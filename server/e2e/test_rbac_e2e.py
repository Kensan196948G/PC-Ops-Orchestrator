"""E2E tests for role-based access control in the WebUI."""


def test_admin_sees_user_management_link(page_with_login, live_server):
    """Admin role should see the hidden user management nav link."""
    p = page_with_login
    # base.html shows #nav-users for admin via JS; wait for it
    p.wait_for_selector("#nav-users", state="visible", timeout=5000)
    assert p.is_visible("#nav-users")


def test_viewer_cannot_see_user_management_link(viewer_page, live_server):
    """Viewer role should NOT see the user management nav link."""
    p = viewer_page
    # Give JS time to resolve role; nav-users should remain hidden
    p.wait_for_timeout(2000)
    # Either absent from DOM or display:none
    locator = p.locator("#nav-users")
    visible = locator.is_visible() if locator.count() > 0 else False
    assert not visible, "Viewer should not see user management link"


def test_users_api_admin_access(page_with_login, live_server):
    """Admin should get 200 from /api/auth/users."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")
    assert token, "Token must be set"

    response = p.request.get(
        f"{live_server}/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status == 200


def test_users_api_viewer_denied(viewer_page, live_server):
    """Viewer should get 403 from /api/auth/users."""
    p = viewer_page
    token = p.evaluate("localStorage.getItem('token')")
    assert token, "Token must be set"

    response = p.request.get(
        f"{live_server}/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status == 403


def test_audit_api_admin_access(page_with_login, live_server):
    """Admin should get 200 from /api/audit/logs."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")

    response = p.request.get(
        f"{live_server}/api/audit/logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status == 200
