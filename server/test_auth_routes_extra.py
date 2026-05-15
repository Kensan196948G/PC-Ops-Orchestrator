"""Extra coverage tests for routes/auth_routes.py.

Targets uncovered lines:
- login: no body (28)
- setup: no body (84), no username/password (90), short password (92), success (95-107)
- create_user: no body (123), invalid role (141), duplicate username (150)
- update_user: self-update (167), password update (191)
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_auth_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(User(
                username=username,
                password_hash=hash_password("AdminAuth1!"),
                role="admin",
            ))
        db.session.commit()
    _admin_token = _login(f"admin_auth_{_unique}", "AdminAuth1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


# ── login: no body (line 28) ─────────────────────────────────────────


def test_login_no_body():
    """POST /api/auth/login with null JSON body → 400 (line 28).

    JSON null deserialises to Python None, which is falsy, so the
    'if not data' branch at line 27-28 fires and returns our JSON error.
    """
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=b"null",
    )
    assert r.status_code == 400
    assert "リクエストボディ" in json.loads(r.data)["error"]


def test_login_missing_fields():
    """POST /api/auth/login with empty username/password → 400."""
    r = req("POST", "/api/auth/login", data={"username": "", "password": ""})
    assert r.status_code == 400
    assert "必要" in json.loads(r.data)["error"]


def test_login_wrong_password():
    """POST /api/auth/login with wrong password → 401."""
    r = req("POST", "/api/auth/login", data={
        "username": f"admin_auth_{_unique}",
        "password": "WrongPassword1!",
    })
    assert r.status_code == 401


def test_login_nonexistent_user():
    """POST /api/auth/login with nonexistent user → 401."""
    r = req("POST", "/api/auth/login", data={
        "username": f"nobody_{_unique}",
        "password": "SomePass1!",
    })
    assert r.status_code == 401


def test_login_inactive_account():
    """POST /api/auth/login with inactive account → 403."""
    username = f"inactive_{_unique}"
    with app.app_context():
        u = User(
            username=username,
            password_hash=hash_password("InactivePass1!"),
            role="viewer",
            is_active=False,
        )
        db.session.add(u)
        db.session.commit()
    r = req("POST", "/api/auth/login", data={
        "username": username,
        "password": "InactivePass1!",
    })
    assert r.status_code == 403
    assert "無効" in json.loads(r.data)["error"]


def test_login_locked_account():
    """POST /api/auth/login with locked account → 403."""
    username = f"locked_{_unique}"
    with app.app_context():
        u = User(
            username=username,
            password_hash=hash_password("LockedPass1!"),
            role="viewer",
            is_locked=True,
        )
        db.session.add(u)
        db.session.commit()
    r = req("POST", "/api/auth/login", data={
        "username": username,
        "password": "LockedPass1!",
    })
    assert r.status_code == 403
    assert "ロック" in json.loads(r.data)["error"]


# ── setup: empty-DB paths (lines 83-105) ────────────────────────────


def _fresh_setup_client():
    """Return a test client with a fresh empty in-memory DB."""
    fresh_app = create_app("testing")
    with fresh_app.app_context():
        db.create_all()
    return fresh_app.test_client()


def test_setup_no_body():
    """POST /api/auth/setup with null JSON body → 400 (line 84-85).

    JSON null → Python None → falsy, so 'if not data' fires.
    Uses a fresh app instance so the DB is empty (setup endpoint guard passes).
    """
    c = _fresh_setup_client()
    r = c.open(
        "/api/auth/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=b"null",
    )
    assert r.status_code == 400
    assert "リクエストボディ" in json.loads(r.data)["error"]


def test_setup_missing_fields():
    """POST /api/auth/setup with empty username → 400 (lines 90-91)."""
    c = _fresh_setup_client()
    r = c.open(
        "/api/auth/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "", "password": "Admin1!"}),
    )
    assert r.status_code == 400
    assert "必須" in json.loads(r.data)["error"]


def test_setup_short_password():
    """POST /api/auth/setup with short password → 400 (lines 92-93)."""
    c = _fresh_setup_client()
    r = c.open(
        "/api/auth/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin", "password": "short"}),
    )
    assert r.status_code == 400
    assert "8" in json.loads(r.data)["error"]


def test_setup_success():
    """POST /api/auth/setup with valid data → 201 (lines 95-107)."""
    c = _fresh_setup_client()
    r = c.open(
        "/api/auth/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin", "password": "AdminPass1!"}),
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "user" in data
    assert data["user"]["role"] == "admin"


def test_setup_already_initialized():
    """POST /api/auth/setup when users exist → 400 (line 81)."""
    r = req("POST", "/api/auth/setup", data={
        "username": "admin2",
        "password": "Admin2!@#$",
    })
    assert r.status_code == 400
    assert "初期設定済み" in json.loads(r.data)["error"]


# ── create_user: no body, invalid role, duplicate (lines 123, 141, 150) ──


def test_create_user_no_body():
    """POST /api/auth/users without body → 400 or 415 (line 123)."""
    r = client.open(
        "/api/auth/users",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)


def test_create_user_invalid_role():
    """POST /api/auth/users with invalid role → 400 (line 141)."""
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": f"badroler_{_unique}",
        "password": "ValidPass1!",
        "role": "superuser",
    })
    assert r.status_code == 400
    assert "role" in json.loads(r.data)["error"]


def test_create_user_role_not_string():
    """POST /api/auth/users with role as int → 400."""
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": f"badroletype_{_unique}",
        "password": "ValidPass1!",
        "role": 123,
    })
    assert r.status_code == 400
    assert "role" in json.loads(r.data)["error"]


def test_create_user_duplicate_username():
    """POST /api/auth/users with existing username → 409 (line 150)."""
    existing = f"admin_auth_{_unique}"
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": existing,
        "password": "ValidPass1!",
        "role": "viewer",
    })
    assert r.status_code == 409
    assert "使用されています" in json.loads(r.data)["error"]


def test_create_user_weak_password():
    """POST /api/auth/users with weak password → 400."""
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": f"weakpw_{_unique}",
        "password": "weakpassword",
        "role": "viewer",
    })
    assert r.status_code == 400
    assert "パスワード" in json.loads(r.data)["error"]


def test_create_user_success():
    """POST /api/auth/users valid → 201."""
    username = f"newuser_{_unique}"
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": username,
        "password": "NewUser1!@#",
        "role": "operator",
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["user"]["username"] == username
    user_id = data["user"]["id"]
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


# ── update_user: self-update (167), password update (191) ────────────


def _create_user(suffix, role="viewer"):
    """Create a test user and return (user_id, token)."""
    username = f"usr_{suffix}_{_unique}"
    password = f"UserPass1!{suffix}"
    r = req("POST", "/api/auth/users", token=_admin_token, data={
        "username": username,
        "password": password,
        "role": role,
    })
    assert r.status_code == 201, f"user create failed: {r.data}"
    user_id = json.loads(r.data)["user"]["id"]
    return user_id, username, password


def test_update_user_self_update():
    """PATCH /api/auth/users/<id> self-update → 400 (line 167)."""
    with app.app_context():
        me = User.query.filter_by(username=f"admin_auth_{_unique}").first()
        my_id = me.id
    r = req("PATCH", f"/api/auth/users/{my_id}", token=_admin_token, data={
        "role": "viewer",
    })
    assert r.status_code == 400
    assert "自分自身" in json.loads(r.data)["error"]


def test_update_user_password():
    """PATCH /api/auth/users/<id> with password field → 200 and password updated (line 191)."""
    user_id, username, old_pw = _create_user("pwupd")
    new_pw = "NewPass2@#$"
    r = req("PATCH", f"/api/auth/users/{user_id}", token=_admin_token, data={
        "password": new_pw,
    })
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "ユーザーを更新しました" in data["message"]
    # verify can login with new password
    r2 = req("POST", "/api/auth/login", data={"username": username, "password": new_pw})
    assert r2.status_code == 200
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_update_user_weak_new_password():
    """PATCH /api/auth/users/<id> with weak new password → 400."""
    user_id, _, _ = _create_user("wkpwupd")
    r = req("PATCH", f"/api/auth/users/{user_id}", token=_admin_token, data={
        "password": "weak",
    })
    assert r.status_code == 400
    assert "パスワード" in json.loads(r.data)["error"]
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_update_user_role():
    """PATCH /api/auth/users/<id> with valid role → 200."""
    user_id, _, _ = _create_user("roleupd")
    r = req("PATCH", f"/api/auth/users/{user_id}", token=_admin_token, data={
        "role": "operator",
    })
    assert r.status_code == 200
    assert json.loads(r.data)["user"]["role"] == "operator"
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_update_user_invalid_role():
    """PATCH /api/auth/users/<id> with invalid role → 400."""
    user_id, _, _ = _create_user("invrlupd")
    r = req("PATCH", f"/api/auth/users/{user_id}", token=_admin_token, data={
        "role": "god",
    })
    assert r.status_code == 400
    assert "role" in json.loads(r.data)["error"]
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_update_user_is_active():
    """PATCH /api/auth/users/<id> with is_active=False → 200."""
    user_id, _, _ = _create_user("deactivate")
    r = req("PATCH", f"/api/auth/users/{user_id}", token=_admin_token, data={
        "is_active": False,
    })
    assert r.status_code == 200
    assert json.loads(r.data)["user"]["is_active"] is False
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_update_user_not_found():
    """PATCH /api/auth/users/9999999 → 404."""
    r = req("PATCH", "/api/auth/users/9999999", token=_admin_token, data={"role": "viewer"})
    assert r.status_code == 404


# ── unlock_user ──────────────────────────────────────────────────────


def test_unlock_user_success():
    """POST /api/auth/users/<id>/unlock on locked user → 200."""
    user_id, _, _ = _create_user("lockme")
    with app.app_context():
        from models import User as UserModel
        u = db.session.get(UserModel, user_id)
        u.is_locked = True
        u.failed_login_count = 5
        db.session.commit()
    r = req("POST", f"/api/auth/users/{user_id}/unlock", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "ロックを解除" in data["message"]
    # cleanup
    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_unlock_user_not_found():
    """POST /api/auth/users/9999999/unlock → 404."""
    r = req("POST", "/api/auth/users/9999999/unlock", token=_admin_token)
    assert r.status_code == 404


# ── delete_user ──────────────────────────────────────────────────────


def test_delete_user_self():
    """DELETE /api/auth/users/<own_id> → 400 (cannot delete self)."""
    with app.app_context():
        me = User.query.filter_by(username=f"admin_auth_{_unique}").first()
        my_id = me.id
    r = req("DELETE", f"/api/auth/users/{my_id}", token=_admin_token)
    assert r.status_code == 400
    assert "自分自身" in json.loads(r.data)["error"]


def test_delete_user_not_found():
    """DELETE /api/auth/users/9999999 → 404."""
    r = req("DELETE", "/api/auth/users/9999999", token=_admin_token)
    assert r.status_code == 404


# ── failed login increments counter ─────────────────────────────────


def test_failed_login_increments_count():
    """Repeated bad password increments failed_login_count."""
    username = f"failcount_{_unique}"
    with app.app_context():
        u = User(
            username=username,
            password_hash=hash_password("RealPass1!@#"),
            role="viewer",
        )
        db.session.add(u)
        db.session.commit()
        user_id = u.id

    for _ in range(3):
        req("POST", "/api/auth/login", data={
            "username": username,
            "password": "WrongPass1!",
        })

    with app.app_context():
        u = db.session.get(User, user_id)
        assert u.failed_login_count >= 3
    # cleanup
    with app.app_context():
        u = db.session.get(User, user_id)
        db.session.delete(u)
        db.session.commit()
