"""Phase C-2 (#228) — Monthly report email delivery tests.

Covers:
- POST /api/reports/monthly/send requires admin/operator role
- SMTP not configured → 503
- Invalid format → 400
- Invalid year/month → 400
- Empty recipients list → 400
- recipients as non-list → 400
- format=pdf succeeds with mocked SMTP
- format=csv succeeds with mocked SMTP
- format=both sends both attachments
- recipients omitted, ALERT_EMAIL_TO env fallback
- send_report_email_via_smtp: low-level function unit tests
"""

import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()

_unique = uuid.uuid4().hex[:8]
_admin_token = None
_viewer_token = None


def setup_module():
    global _admin_token, _viewer_token
    with app.app_context():
        db.create_all()
        admin_name = f"rd_admin_{_unique}"
        viewer_name = f"rd_viewer_{_unique}"
        if not User.query.filter_by(username=admin_name).first():
            db.session.add(
                User(
                    username=admin_name,
                    password_hash=hash_password("AdminRD1!"),
                    role="admin",
                )
            )
        if not User.query.filter_by(username=viewer_name).first():
            db.session.add(
                User(
                    username=viewer_name,
                    password_hash=hash_password("ViewerRD1!"),
                    role="viewer",
                )
            )
        db.session.commit()

    _admin_token = _login(f"rd_admin_{_unique}", "AdminRD1!")
    _viewer_token = _login(f"rd_viewer_{_unique}", "ViewerRD1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _post(payload, token=None, env_overrides=None):
    """POST /api/reports/monthly/send with optional env overrides."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    env_overrides = env_overrides or {}
    saved = {k: os.environ.pop(k, None) for k in env_overrides}
    for k, v in env_overrides.items():
        os.environ[k] = v
    try:
        return client.open(
            "/api/reports/monthly/send",
            method="POST",
            headers=headers,
            data=json.dumps(payload),
        )
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Ensure SMTP_HOST is cleaned up if it was set but not in saved
        for k in env_overrides:
            if saved.get(k) is None and k in os.environ:
                os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_send_requires_auth():
    r = client.open(
        "/api/reports/monthly/send",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"year": 2026, "month": 5}),
    )
    assert r.status_code == 401


def test_send_viewer_forbidden():
    """viewer role cannot POST /monthly/send (operator+ required)."""
    # Ensure no SMTP_HOST so we don't accidentally hit SMTP check first
    os.environ.pop("SMTP_HOST", None)
    r = client.open(
        "/api/reports/monthly/send",
        method="POST",
        headers={
            "Content-Type": "application/json",
            **_auth(_viewer_token),
        },
        data=json.dumps({"year": 2026, "month": 5}),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Input validation (no SMTP needed — fails before SMTP check)
# ---------------------------------------------------------------------------


def test_send_invalid_format():
    os.environ.pop("SMTP_HOST", None)
    r = _post({"year": 2026, "month": 5, "format": "xlsx"}, token=_admin_token)
    assert r.status_code == 400
    assert "format" in r.get_json()["error"]


def test_send_invalid_month():
    os.environ.pop("SMTP_HOST", None)
    r = _post({"year": 2026, "month": 13}, token=_admin_token)
    assert r.status_code == 400


def test_send_invalid_year():
    os.environ.pop("SMTP_HOST", None)
    r = _post({"year": 1999, "month": 5}, token=_admin_token)
    assert r.status_code == 400


def test_send_empty_recipients():
    os.environ.pop("SMTP_HOST", None)
    r = _post(
        {"year": 2026, "month": 5, "recipients": []},
        token=_admin_token,
    )
    assert r.status_code == 400
    assert "recipients" in r.get_json()["error"]


def test_send_recipients_not_list():
    os.environ.pop("SMTP_HOST", None)
    r = _post(
        {"year": 2026, "month": 5, "recipients": "single@example.com"},
        token=_admin_token,
    )
    assert r.status_code == 400


def test_send_year_month_not_int():
    os.environ.pop("SMTP_HOST", None)
    r = _post({"year": "two-thousand", "month": 5}, token=_admin_token)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# SMTP not configured → 503
# ---------------------------------------------------------------------------


def test_send_smtp_not_configured():
    """When SMTP_HOST is absent, endpoint must return 503."""
    os.environ.pop("SMTP_HOST", None)
    r = _post({"year": 2026, "month": 5, "format": "pdf"}, token=_admin_token)
    assert r.status_code == 503
    assert "SMTP" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# Successful delivery (mocked SMTP)
# ---------------------------------------------------------------------------


def _mock_smtp_ctx():
    """Return a context manager that patches smtplib.SMTP to a MagicMock."""
    mock_server = MagicMock()
    mock_server.__enter__ = MagicMock(return_value=mock_server)
    mock_server.__exit__ = MagicMock(return_value=False)
    return patch("smtplib.SMTP", return_value=mock_server), mock_server


def test_send_pdf_success():
    smtp_patch, mock_server = _mock_smtp_ctx()
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user@example.com",
        "SMTP_PASSWORD": "secret",
        "ALERT_EMAIL_FROM": "noreply@example.com",
        "ALERT_EMAIL_TO": "admin@example.com",
    }
    saved = {k: os.environ.pop(k, None) for k in env}
    for k, v in env.items():
        os.environ[k] = v
    try:
        with smtp_patch:
            r = client.open(
                "/api/reports/monthly/send",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **_auth(_admin_token),
                },
                data=json.dumps({"year": 2026, "month": 5, "format": "pdf"}),
            )
        assert r.status_code == 200
        body = r.get_json()
        assert body["format"] == "pdf"
        assert body["year"] == 2026
        assert body["month"] == 5
        assert "sent_at" in body
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_send_csv_success():
    smtp_patch, _ = _mock_smtp_ctx()
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "user@example.com",
        "SMTP_PASSWORD": "pass",
        "ALERT_EMAIL_FROM": "noreply@example.com",
        "ALERT_EMAIL_TO": "ops@example.com",
    }
    saved = {k: os.environ.pop(k, None) for k in env}
    for k, v in env.items():
        os.environ[k] = v
    try:
        with smtp_patch:
            r = client.open(
                "/api/reports/monthly/send",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **_auth(_admin_token),
                },
                data=json.dumps({"year": 2026, "month": 4, "format": "csv"}),
            )
        assert r.status_code == 200
        assert r.get_json()["format"] == "csv"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_send_both_success():
    smtp_patch, mock_server = _mock_smtp_ctx()
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "u@example.com",
        "SMTP_PASSWORD": "pw",
        "ALERT_EMAIL_FROM": "noreply@example.com",
        "ALERT_EMAIL_TO": "admin@example.com",
    }
    saved = {k: os.environ.pop(k, None) for k in env}
    for k, v in env.items():
        os.environ[k] = v
    try:
        with smtp_patch:
            r = client.open(
                "/api/reports/monthly/send",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **_auth(_admin_token),
                },
                data=json.dumps({"year": 2026, "month": 3, "format": "both"}),
            )
        assert r.status_code == 200
        assert r.get_json()["format"] == "both"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_send_explicit_recipients():
    """Explicit recipients list overrides ALERT_EMAIL_TO."""
    smtp_patch, _ = _mock_smtp_ctx()
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "ALERT_EMAIL_FROM": "noreply@example.com",
        "ALERT_EMAIL_TO": "default@example.com",
    }
    saved = {k: os.environ.pop(k, None) for k in env}
    for k, v in env.items():
        os.environ[k] = v
    try:
        with smtp_patch:
            r = client.open(
                "/api/reports/monthly/send",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **_auth(_admin_token),
                },
                data=json.dumps(
                    {
                        "year": 2026,
                        "month": 5,
                        "format": "csv",
                        "recipients": ["custom@example.com", "mgr@example.com"],
                    }
                ),
            )
        assert r.status_code == 200
        body = r.get_json()
        assert "custom@example.com" in body["recipients"]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Low-level function unit tests
# ---------------------------------------------------------------------------


def test_send_report_email_via_smtp_no_host():
    from notify import send_report_email_via_smtp

    result = send_report_email_via_smtp(
        host="",
        port=587,
        user="",
        password="",
        from_addr="noreply@example.com",
        to_addrs=["a@b.com"],
        year=2026,
        month=5,
    )
    assert result is False


def test_send_report_email_via_smtp_no_recipients():
    from notify import send_report_email_via_smtp

    result = send_report_email_via_smtp(
        host="smtp.example.com",
        port=587,
        user="",
        password="",
        from_addr="noreply@example.com",
        to_addrs=[],
        year=2026,
        month=5,
    )
    assert result is False


def test_send_report_email_via_smtp_smtp_error():
    """SMTPException is caught and returns False (no exception raised)."""
    import smtplib

    from notify import send_report_email_via_smtp

    with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("conn refused")):
        result = send_report_email_via_smtp(
            host="smtp.example.com",
            port=587,
            user="u",
            password="p",
            from_addr="noreply@example.com",
            to_addrs=["admin@example.com"],
            year=2026,
            month=5,
            csv_bytes=b"col,val\n",
        )
    assert result is False


def test_send_report_email_no_smtp_host_env():
    """send_report_email returns False when SMTP_HOST env is missing."""
    from notify import send_report_email

    saved = os.environ.pop("SMTP_HOST", None)
    try:
        result = send_report_email(year=2026, month=5)
        assert result is False
    finally:
        if saved is not None:
            os.environ["SMTP_HOST"] = saved
