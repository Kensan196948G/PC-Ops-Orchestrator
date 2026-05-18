"""Tests for Phase C-4 admin operations endpoints (Issue #236)."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import User

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


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────
# POST /api/admin/backup/db
# ──────────────────────────────────────────────


def test_backup_db_requires_admin():
    resp = client.post("/api/admin/backup/db")
    assert resp.status_code == 401


def test_backup_db_no_db_file_returns_404(admin_token, tmp_path):
    """When the DB path does not exist, the endpoint must return 404."""
    with app.app_context():
        from routes.admin_ops import _db_path

        original = _db_path()
        # :memory: DB → resolved path won't exist unless we create it
        if not original.exists():
            resp = client.post("/api/admin/backup/db", headers=_headers(admin_token))
            assert resp.status_code == 404
            return
    # file-based DB: ensure backup succeeds (tested separately)
    resp = client.post("/api/admin/backup/db", headers=_headers(admin_token))
    assert resp.status_code in (201, 404)


def test_backup_db_with_real_file(admin_token, tmp_path):
    """Create a real SQLite file and verify the backup endpoint works."""
    src = tmp_path / "pc_ops.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.close()

    with app.test_request_context():
        import flask

        with flask.current_app.test_request_context():
            pass

    # Patch _db_path and _backup_dir via monkeypatching
    import routes.admin_ops as mod

    original_db_path = mod._db_path
    original_backup_dir = mod._backup_dir

    bdir = tmp_path / "backups"
    bdir.mkdir()

    def _fake_db_path():
        return src

    def _fake_backup_dir():
        return bdir

    mod._db_path = _fake_db_path
    mod._backup_dir = _fake_backup_dir
    try:
        resp = client.post("/api/admin/backup/db", headers=_headers(admin_token))
    finally:
        mod._db_path = original_db_path
        mod._backup_dir = original_backup_dir

    assert resp.status_code == 201
    data = resp.get_json()
    assert "filename" in data
    assert data["filename"].startswith("pc_ops_")
    assert data["size_bytes"] > 0


# ──────────────────────────────────────────────
# GET /api/admin/backup/list
# ──────────────────────────────────────────────


def test_backup_list_requires_admin():
    resp = client.get("/api/admin/backup/list")
    assert resp.status_code == 401


def test_backup_list_returns_json(admin_token):
    resp = client.get("/api/admin/backup/list", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "backups" in data
    assert "total" in data
    assert isinstance(data["backups"], list)


def test_backup_list_with_files(admin_token, tmp_path):
    """Verify list returns correct metadata for existing backup files."""
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for name in ["pc_ops_20260101T000000Z.db", "pc_ops_20260102T000000Z.db"]:
        f = bdir / name
        conn = sqlite3.connect(str(f))
        conn.close()

    import routes.admin_ops as mod

    original = mod._backup_dir
    mod._backup_dir = lambda: bdir
    try:
        resp = client.get("/api/admin/backup/list", headers=_headers(admin_token))
    finally:
        mod._backup_dir = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert all("filename" in b for b in data["backups"])


def test_backup_rotation(admin_token, tmp_path):
    """After creating 11 backups, only 10 should remain."""
    src = tmp_path / "pc_ops.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.close()

    bdir = tmp_path / "backups"
    bdir.mkdir()

    import routes.admin_ops as mod

    mod._db_path = lambda: src
    mod._backup_dir = lambda: bdir
    try:
        for _ in range(11):
            resp = client.post("/api/admin/backup/db", headers=_headers(admin_token))
            assert resp.status_code == 201
        files = list(bdir.glob("pc_ops_*.db"))
        assert len(files) <= 10
    finally:
        import routes.admin_ops as fresh_mod

        fresh_mod._db_path = mod.__class__.__dict__.get("_db_path", mod._db_path)
        # restore by reloading defaults
        import importlib

        importlib.reload(fresh_mod)


# ──────────────────────────────────────────────
# GET /api/admin/logs/app
# ──────────────────────────────────────────────


def test_logs_app_requires_admin():
    resp = client.get("/api/admin/logs/app")
    assert resp.status_code == 401


def test_logs_app_missing_file(admin_token, tmp_path):
    import routes.admin_ops as mod

    original = mod._ACCESS_LOG
    mod._ACCESS_LOG = str(tmp_path / "nonexistent.log")
    try:
        resp = client.get("/api/admin/logs/app", headers=_headers(admin_token))
    finally:
        mod._ACCESS_LOG = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lines"] == []
    assert data["count"] == 0


def test_logs_app_returns_lines(admin_token, tmp_path):
    log_file = tmp_path / "access.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(200)))

    import routes.admin_ops as mod

    original = mod._ACCESS_LOG
    mod._ACCESS_LOG = str(log_file)
    try:
        resp = client.get("/api/admin/logs/app?lines=50", headers=_headers(admin_token))
    finally:
        mod._ACCESS_LOG = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 50


def test_logs_app_max_lines_cap(admin_token, tmp_path):
    log_file = tmp_path / "access.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(2000)))

    import routes.admin_ops as mod

    original = mod._ACCESS_LOG
    mod._ACCESS_LOG = str(log_file)
    try:
        resp = client.get(
            "/api/admin/logs/app?lines=9999", headers=_headers(admin_token)
        )
    finally:
        mod._ACCESS_LOG = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] <= 1000


# ──────────────────────────────────────────────
# GET /api/admin/logs/error
# ──────────────────────────────────────────────


def test_logs_error_requires_admin():
    resp = client.get("/api/admin/logs/error")
    assert resp.status_code == 401


def test_logs_error_missing_file(admin_token, tmp_path):
    import routes.admin_ops as mod

    original = mod._ERROR_LOG
    mod._ERROR_LOG = str(tmp_path / "nonexistent.log")
    try:
        resp = client.get("/api/admin/logs/error", headers=_headers(admin_token))
    finally:
        mod._ERROR_LOG = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lines"] == []


def test_logs_error_returns_lines(admin_token, tmp_path):
    log_file = tmp_path / "error.log"
    log_file.write_text("ERROR: something went wrong\nWARN: minor issue\n")

    import routes.admin_ops as mod

    original = mod._ERROR_LOG
    mod._ERROR_LOG = str(log_file)
    try:
        resp = client.get("/api/admin/logs/error", headers=_headers(admin_token))
    finally:
        mod._ERROR_LOG = original

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] >= 1


# ──────────────────────────────────────────────
# HSTS header (C-4-1: already implemented in app.py)
# ──────────────────────────────────────────────


def test_hsts_absent_in_testing():
    """HSTS must NOT be set outside production config (HTTP dev/test environments)."""
    resp = client.get("/api/ad/config")
    assert "Strict-Transport-Security" not in resp.headers
