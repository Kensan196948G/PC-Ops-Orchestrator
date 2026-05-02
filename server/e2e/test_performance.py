"""Performance tests — page load times and API response times (items 86-100)."""

import time
import json


def _get_admin_token(page, live_server):
    """Helper: login and return the JWT token string."""
    page.goto(f"{live_server}/login")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    token = page.evaluate("localStorage.getItem('token')")
    assert token, "Token must be present after login"
    return token


def test_health_endpoint_fast_response(page, live_server):
    """GET /health must respond in under 2 seconds."""
    start = time.time()
    response = page.goto(f"{live_server}/health")
    elapsed = time.time() - start
    assert response is not None
    assert response.status == 200
    assert elapsed < 2.0, f"/health took {elapsed:.2f}s, expected < 2s"


def test_login_page_loads_within_5_seconds(page, live_server):
    """Login page must fully load within 5 seconds."""
    start = time.time()
    page.goto(f"{live_server}/login")
    page.wait_for_load_state("domcontentloaded", timeout=5000)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Login page took {elapsed:.2f}s"


def test_dashboard_loads_within_5_seconds(page_with_login, live_server):
    """Dashboard must reach domcontentloaded within 5 seconds."""
    p = page_with_login
    start = time.time()
    p.goto(f"{live_server}/")
    p.wait_for_load_state("domcontentloaded", timeout=5000)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Dashboard took {elapsed:.2f}s"


def test_api_auth_login_responds_within_2_seconds(page, live_server):
    """POST /api/auth/login must respond within 2 seconds."""
    start = time.time()
    response = page.request.post(
        f"{live_server}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin"}),
        headers={"Content-Type": "application/json"},
    )
    elapsed = time.time() - start
    assert response.status == 200
    assert elapsed < 2.0, f"/api/auth/login took {elapsed:.2f}s"


def test_api_dashboard_stats_responds_within_2_seconds(page_with_login, live_server):
    """GET /api/dashboard/stats must respond within 2 seconds."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")
    start = time.time()
    response = p.request.get(
        f"{live_server}/api/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.time() - start
    assert response.status == 200
    assert elapsed < 2.0, f"/api/dashboard/stats took {elapsed:.2f}s"


def test_api_pcs_list_responds_within_2_seconds(page_with_login, live_server):
    """GET /api/pcs must respond within 2 seconds."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")
    start = time.time()
    response = p.request.get(
        f"{live_server}/api/pcs",
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.time() - start
    assert response.status == 200
    assert elapsed < 2.0, f"/api/pcs took {elapsed:.2f}s"


def test_api_tasks_list_responds_within_2_seconds(page_with_login, live_server):
    """GET /api/tasks must respond within 2 seconds."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")
    start = time.time()
    response = p.request.get(
        f"{live_server}/api/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.time() - start
    assert response.status == 200
    assert elapsed < 2.0, f"/api/tasks took {elapsed:.2f}s"


def test_api_alerts_list_responds_within_2_seconds(page_with_login, live_server):
    """GET /api/alerts must respond within 2 seconds."""
    p = page_with_login
    token = p.evaluate("localStorage.getItem('token')")
    start = time.time()
    response = p.request.get(
        f"{live_server}/api/alerts",
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.time() - start
    assert response.status == 200
    assert elapsed < 2.0, f"/api/alerts took {elapsed:.2f}s"


def test_static_css_responds_within_2_seconds(page, live_server):
    """GET /static/css/style.css must respond within 2 seconds with status 200."""
    start = time.time()
    response = page.goto(f"{live_server}/static/css/style.css")
    elapsed = time.time() - start
    assert response is not None
    assert response.status == 200
    assert elapsed < 2.0, f"style.css took {elapsed:.2f}s"


def test_static_js_dashboard_responds_within_2_seconds(page, live_server):
    """GET /static/js/dashboard.js must respond within 2 seconds with status 200."""
    start = time.time()
    response = page.goto(f"{live_server}/static/js/dashboard.js")
    elapsed = time.time() - start
    assert response is not None
    assert response.status == 200
    assert elapsed < 2.0, f"dashboard.js took {elapsed:.2f}s"


def test_no_network_errors_on_dashboard_load(page, live_server):
    """
    Dashboard page load must not generate any failed network requests.
    Uses a fresh page (not page_with_login) to observe ALL requests from the
    initial navigation, avoiding mid-flight cancellations from a prior goto.
    """
    failed_requests = []

    def on_request_failed(req):
        # Ignore external CDN failures that may occur in offline environments
        if "127.0.0.1" in req.url or "localhost" in req.url:
            failed_requests.append(req.url)

    page.on("requestfailed", on_request_failed)

    # Login first
    page.goto(f"{live_server}/login")
    page.fill("#username", "admin")
    page.fill("#password", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server}/", timeout=8000)
    page.wait_for_load_state("networkidle", timeout=10000)

    assert not failed_requests, f"Failed requests on dashboard: {failed_requests}"


def test_pcs_page_loads_within_5_seconds(page_with_login, live_server):
    """PC list page must load within 5 seconds."""
    p = page_with_login
    start = time.time()
    p.goto(f"{live_server}/pcs")
    p.wait_for_load_state("domcontentloaded", timeout=5000)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"/pcs took {elapsed:.2f}s"


def test_health_response_body_structure(page, live_server):
    """Health endpoint must return JSON with status and db fields."""
    response = page.goto(f"{live_server}/health")
    assert response is not None
    assert response.status == 200
    body = json.loads(response.body())
    assert "status" in body
    assert body["status"] == "ok"
    assert "db" in body
