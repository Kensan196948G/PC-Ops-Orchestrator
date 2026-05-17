"""Tests for Phase C-3 AD sync endpoints (Issue #230)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch

from app import create_app
from auth import hash_password
from extensions import db
from models import SystemSetting, User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            db.session.add(
                User(
                    username="admin", password_hash=hash_password("admin"), role="admin"
                )
            )
            db.session.commit()


@pytest.fixture(scope="module")
def admin_token():
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    return r.get_json()["token"]


def _ad_settings():
    with app.app_context():
        for key, value in {
            "ad_host": "ldap.example.com",
            "ad_port": "389",
            "ad_use_ssl": "false",
            "ad_bind_dn": "CN=svc,DC=example,DC=com",
            "ad_bind_password": "secret",
            "ad_base_dn": "DC=example,DC=com",
            "ad_user_filter": "(&(objectClass=user)(objectCategory=person))",
            "ad_default_role": "viewer",
        }.items():
            row = SystemSetting.query.get(key)
            if row:
                row.value = value
            else:
                db.session.add(SystemSetting(key=key, value=value))
        db.session.commit()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────
# GET /api/ad/config
# ──────────────────────────────────────────────


def test_get_ad_config_requires_admin():
    resp = client.get("/api/ad/config")
    assert resp.status_code == 401


def test_get_ad_config_returns_masked_password(admin_token):
    _ad_settings()
    resp = client.get("/api/ad/config", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "config" in data
    assert data["config"]["ad_bind_password"] == "***"
    assert data["config"]["ad_host"] == "ldap.example.com"


# ──────────────────────────────────────────────
# PUT /api/ad/config
# ──────────────────────────────────────────────


def test_update_ad_config_valid(admin_token):
    resp = client.put(
        "/api/ad/config",
        json={"ad_host": "new-ldap.example.com", "ad_port": "636"},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["config"]["ad_host"] == "new-ldap.example.com"


def test_update_ad_config_rejects_unknown_keys(admin_token):
    resp = client.put(
        "/api/ad/config",
        json={"ad_host": "ok.com", "unknown_key": "bad"},
        headers=_headers(admin_token),
    )
    assert resp.status_code == 400
    assert "不明なキー" in resp.get_json()["error"]


def test_update_ad_config_requires_admin():
    resp = client.put("/api/ad/config", json={"ad_host": "x.com"})
    assert resp.status_code == 401


# ──────────────────────────────────────────────
# GET /api/ad/status
# ──────────────────────────────────────────────


def test_ad_status_no_host_returns_503(admin_token):
    with app.app_context():
        row = SystemSetting.query.get("ad_host")
        if row:
            row.value = ""
        db.session.commit()
    resp = client.get("/api/ad/status", headers=_headers(admin_token))
    assert resp.status_code == 503
    assert resp.get_json()["connected"] is False


def test_ad_status_connection_ok(admin_token):
    _ad_settings()
    with patch(
        "ad_client.test_ad_connection", return_value=(True, "Connected successfully")
    ):
        resp = client.get("/api/ad/status", headers=_headers(admin_token))
    assert resp.status_code == 200
    assert resp.get_json()["connected"] is True


def test_ad_status_connection_failure(admin_token):
    _ad_settings()
    with patch(
        "ad_client.test_ad_connection", return_value=(False, "Connection refused")
    ):
        resp = client.get("/api/ad/status", headers=_headers(admin_token))
    assert resp.status_code == 503
    assert resp.get_json()["connected"] is False


def test_ad_status_requires_admin():
    resp = client.get("/api/ad/status")
    assert resp.status_code == 401


# ──────────────────────────────────────────────
# POST /api/ad/sync
# ──────────────────────────────────────────────


def test_sync_no_host_returns_503(admin_token):
    with app.app_context():
        row = SystemSetting.query.get("ad_host")
        if row:
            row.value = ""
        db.session.commit()
    resp = client.post("/api/ad/sync", headers=_headers(admin_token))
    assert resp.status_code == 503


def test_sync_creates_new_users(admin_token):
    _ad_settings()
    fake_users = [
        {
            "dn": "CN=alice,DC=example,DC=com",
            "username": "alice_ad_test",
            "display_name": "Alice",
            "email": "alice@example.com",
            "disabled": False,
        }
    ]
    with patch("ad_client.search_ad_users", return_value=fake_users):
        resp = client.post("/api/ad/sync", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["created"] == 1
    assert data["updated"] == 0
    assert data["total_ad_users"] == 1
    with app.app_context():
        user = User.query.filter_by(username="alice_ad_test").first()
        assert user is not None
        assert user.ad_dn == "CN=alice,DC=example,DC=com"


def test_sync_updates_existing_users(admin_token):
    _ad_settings()
    fake_users = [
        {
            "dn": "CN=alice-updated,DC=example,DC=com",
            "username": "alice_ad_test",
            "display_name": "Alice Updated",
            "email": "alice@example.com",
            "disabled": False,
        }
    ]
    with patch("ad_client.search_ad_users", return_value=fake_users):
        resp = client.post("/api/ad/sync", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["created"] == 0
    assert data["updated"] == 1
    with app.app_context():
        user = User.query.filter_by(username="alice_ad_test").first()
        assert user.ad_dn == "CN=alice-updated,DC=example,DC=com"


def test_sync_skips_empty_usernames(admin_token):
    _ad_settings()
    fake_users = [
        {
            "dn": "CN=empty,DC=example,DC=com",
            "username": " ",
            "display_name": "",
            "email": "",
            "disabled": False,
        },
    ]
    with patch("ad_client.search_ad_users", return_value=fake_users):
        resp = client.post("/api/ad/sync", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["created"] == 0
    assert data["updated"] == 0


def test_sync_ad_connection_failure_returns_503(admin_token):
    _ad_settings()
    with patch("ad_client.search_ad_users", return_value=None):
        resp = client.post("/api/ad/sync", headers=_headers(admin_token))
    assert resp.status_code == 503


def test_sync_requires_admin():
    resp = client.post("/api/ad/sync")
    assert resp.status_code == 401
