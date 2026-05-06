"""Tests for M5-5 user security features: account lock, unlock, password policy."""

import sys
import os
import json

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            db.session.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin"),
                    role="admin",
                )
            )
            db.session.commit()


@pytest.fixture(scope="module")
def admin_token():
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/json"},
    )
    return json.loads(r.data)["token"]


def auth(path, method="GET", token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body) if body is not None else None
    return client.open(path, method=method, headers=h, data=data)


# ── password policy ───────────────────────────────────


def test_weak_password_rejected(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "weakpw",
            "password": "simple123",
            "role": "viewer",
        },
    )
    assert r.status_code == 400
    assert "パスワード" in r.get_json()["error"]


def test_strong_password_accepted(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "strongpw_user",
            "password": "StrongPass1!",
            "role": "viewer",
        },
    )
    assert r.status_code == 201
    uid = r.get_json()["user"]["id"]
    auth(f"/api/auth/users/{uid}", "DELETE", admin_token)


# ── login last_login update ────────────────────────────


def test_last_login_set_after_login(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "ll_test_user",
            "password": "LastLog1!",
            "role": "viewer",
        },
    )
    assert r.status_code == 201
    uid = r.get_json()["user"]["id"]
    assert r.get_json()["user"]["last_login"] is None

    client.post(
        "/api/auth/login",
        json={"username": "ll_test_user", "password": "LastLog1!"},
        headers={"Content-Type": "application/json"},
    )

    r2 = client.get(
        "/api/auth/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    users = {u["id"]: u for u in r2.get_json()["users"]}
    assert users[uid]["last_login"] is not None

    auth(f"/api/auth/users/{uid}", "DELETE", admin_token)


# ── account lock after 5 failures ────────────────────


def test_account_locks_after_5_failures(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "lock_target",
            "password": "LockMe99!",
            "role": "viewer",
        },
    )
    assert r.status_code == 201
    uid = r.get_json()["user"]["id"]

    for _ in range(5):
        client.post(
            "/api/auth/login",
            json={"username": "lock_target", "password": "WrongPass!"},
            headers={"Content-Type": "application/json"},
        )

    r2 = client.post(
        "/api/auth/login",
        json={"username": "lock_target", "password": "LockMe99!"},
        headers={"Content-Type": "application/json"},
    )
    assert r2.status_code == 403
    body = r2.get_json()
    assert "ロック" in body["error"]

    users_r = client.get(
        "/api/auth/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    users = {u["id"]: u for u in users_r.get_json()["users"]}
    assert users[uid]["is_locked"] is True
    assert users[uid]["failed_login_count"] >= 5

    auth(f"/api/auth/users/{uid}", "DELETE", admin_token)


# ── unlock endpoint ───────────────────────────────────


def test_unlock_user(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "unlock_target",
            "password": "Unlock99!",
            "role": "viewer",
        },
    )
    uid = r.get_json()["user"]["id"]

    for _ in range(5):
        client.post(
            "/api/auth/login",
            json={"username": "unlock_target", "password": "Wrong!Pass"},
            headers={"Content-Type": "application/json"},
        )

    r2 = auth(f"/api/auth/users/{uid}/unlock", "POST", admin_token)
    assert r2.status_code == 200
    assert r2.get_json()["user"]["is_locked"] is False
    assert r2.get_json()["user"]["failed_login_count"] == 0

    r3 = client.post(
        "/api/auth/login",
        json={"username": "unlock_target", "password": "Unlock99!"},
        headers={"Content-Type": "application/json"},
    )
    assert r3.status_code == 200

    auth(f"/api/auth/users/{uid}", "DELETE", admin_token)


def test_unlock_nonexistent_user(admin_token):
    r = auth("/api/auth/users/99999/unlock", "POST", admin_token)
    assert r.status_code == 404


# ── new user fields in response ────────────────────────


def test_user_to_dict_includes_new_fields(admin_token):
    r = auth(
        "/api/auth/users",
        "POST",
        admin_token,
        {
            "username": "field_check",
            "password": "FieldCheck1!",
            "role": "viewer",
        },
    )
    u = r.get_json()["user"]
    assert "last_login" in u
    assert "failed_login_count" in u
    assert "is_locked" in u
    assert "locked_at" in u
    uid = u["id"]
    auth(f"/api/auth/users/{uid}", "DELETE", admin_token)
