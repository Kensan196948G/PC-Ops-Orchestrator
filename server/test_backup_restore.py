"""Tests for the Phase H-3 backup/restore integrity subsystem (Issue #285).

Covers:
  - trigger_backup creating a real file + BackupJob ledger (no random),
  - trigger_backup failure path,
  - restore round-trip with integrity verification,
  - path-traversal hardening on restore and download,
  - missing-file handling,
  - download happy path,
  - verify_integrity for sqlite + non-sqlite branches.
"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import backup_service
from app import create_app
from auth import hash_password
from extensions import db
from models import BackupJob, User

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


def _make_sqlite_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# trigger_backup (POST /api/backups/trigger)
# ──────────────────────────────────────────────


def test_trigger_backup_creates_real_file(admin_token, tmp_path, monkeypatch):
    """trigger_backup must create a real file and record BackupJob success."""
    src = tmp_path / "pc_ops.db"
    _make_sqlite_db(src)
    bdir = tmp_path / "backups"
    bdir.mkdir()

    monkeypatch.setattr(backup_service, "db_path", lambda: src)
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.post("/api/backups/trigger", headers=_headers(admin_token))
    assert resp.status_code == 201
    data = resp.get_json()["backup"]
    assert data["status"] == "success"
    assert data["size_bytes"] > 0
    assert data["storage_path"]
    # storage_path points to a real, on-disk file under the backup dir.
    assert os.path.exists(data["storage_path"])
    assert os.path.dirname(data["storage_path"]) == str(bdir)
    # duration is a real integer (>= 0), not a fabricated random number.
    assert isinstance(data["duration_seconds"], int)

    with app.app_context():
        job = db.session.get(BackupJob, data["id"])
        assert job is not None
        assert job.status == "success"


def test_trigger_backup_is_not_random():
    """The backups route must not depend on the random module (no fabrication)."""
    import routes.backups as backups_mod

    src = os.path.join(os.path.dirname(backups_mod.__file__), "backups.py")
    with open(src, encoding="utf-8") as fh:
        content = fh.read()
    assert "import random" not in content
    assert "s3://pc-ops-backups" not in content


def test_trigger_backup_failure_marks_job_failed(admin_token, monkeypatch):
    """When perform_backup raises, the job is marked failed and 500 returned."""

    def _boom(*args, **kwargs):
        raise FileNotFoundError("source database not found")

    monkeypatch.setattr(backup_service, "perform_backup", _boom)

    resp = client.post("/api/backups/trigger", headers=_headers(admin_token))
    assert resp.status_code == 500
    data = resp.get_json()["backup"]
    assert data["status"] == "failed"
    assert data["notes"]

    with app.app_context():
        job = db.session.get(BackupJob, data["id"])
        assert job.status == "failed"


def test_trigger_backup_requires_admin():
    resp = client.post("/api/backups/trigger")
    assert resp.status_code == 401


# ──────────────────────────────────────────────
# restore (POST /api/admin/backup/restore)
# ──────────────────────────────────────────────


def test_restore_round_trip(admin_token, tmp_path, monkeypatch):
    """Create a backup, then restore it and confirm integrity passes."""
    src = tmp_path / "pc_ops.db"
    _make_sqlite_db(src)
    bdir = tmp_path / "backups"
    bdir.mkdir()

    monkeypatch.setattr(backup_service, "db_path", lambda: src)
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)
    # Keep the active testing engine's integrity check (in-memory => "ok")
    # rather than probing the swapped file, so the route logic is exercised
    # end-to-end deterministically.
    monkeypatch.setattr(
        backup_service, "verify_integrity", lambda: {"ok": True, "result": ["ok"]}
    )

    # Create a backup to restore from.
    created = client.post("/api/admin/backup/db", headers=_headers(admin_token))
    assert created.status_code == 201
    filename = created.get_json()["filename"]

    resp = client.post(
        "/api/admin/backup/restore",
        headers=_headers(admin_token),
        json={"filename": filename},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["restored_from"] == filename
    assert data["integrity_ok"] is True
    # A pre-restore snapshot must have been auto-created with its own prefix.
    assert data["pre_restore_backup"].startswith("pre_restore_")
    assert (bdir / data["pre_restore_backup"]).exists()


def test_restore_requires_admin():
    resp = client.post("/api/admin/backup/restore", json={"filename": "pc_ops_x.db"})
    assert resp.status_code == 401


def test_restore_missing_filename_returns_400(admin_token):
    resp = client.post(
        "/api/admin/backup/restore", headers=_headers(admin_token), json={}
    )
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "pc_ops_x/../y",
        "pc_ops_../x.db",
        "/etc/passwd",
        "..\\..\\windows\\system32",
        "pre_restore_20260101T000000Z.db",  # snapshot prefix not restorable
        "pc_ops_x.txt",
        "",
    ],
)
def test_restore_path_traversal_returns_400(admin_token, tmp_path, monkeypatch, bad):
    """Path-traversal / malformed filenames must be rejected with 400."""
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.post(
        "/api/admin/backup/restore",
        headers=_headers(admin_token),
        json={"filename": bad},
    )
    assert resp.status_code == 400


def test_restore_nonexistent_file_returns_404(admin_token, tmp_path, monkeypatch):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    src = tmp_path / "pc_ops.db"
    _make_sqlite_db(src)
    monkeypatch.setattr(backup_service, "db_path", lambda: src)
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.post(
        "/api/admin/backup/restore",
        headers=_headers(admin_token),
        json={"filename": "pc_ops_20260101T000000Z.db"},
    )
    assert resp.status_code == 404


def test_restore_integrity_failure_rolls_back(admin_token, tmp_path, monkeypatch):
    """Failing integrity check => rollback from pre-restore snapshot + 500."""
    src = tmp_path / "pc_ops.db"
    _make_sqlite_db(src)
    bdir = tmp_path / "backups"
    bdir.mkdir()

    monkeypatch.setattr(backup_service, "db_path", lambda: src)
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    created = client.post("/api/admin/backup/db", headers=_headers(admin_token))
    filename = created.get_json()["filename"]

    monkeypatch.setattr(
        backup_service,
        "verify_integrity",
        lambda: {"ok": False, "result": ["malformed"]},
    )

    resp = client.post(
        "/api/admin/backup/restore",
        headers=_headers(admin_token),
        json={"filename": filename},
    )
    assert resp.status_code == 500
    # Original DB must still exist (rolled back from snapshot).
    assert src.exists()


# ──────────────────────────────────────────────
# download (GET /api/admin/backup/download)
# ──────────────────────────────────────────────


def test_download_happy_path(admin_token, tmp_path, monkeypatch):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    target = bdir / "pc_ops_20260101T000000Z.db"
    _make_sqlite_db(target)

    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.get(
        "/api/admin/backup/download?filename=pc_ops_20260101T000000Z.db",
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200
    assert len(resp.data) > 0


def test_download_requires_admin():
    resp = client.get("/api/admin/backup/download?filename=pc_ops_x.db")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "pc_ops_x/../y",
        "pc_ops_../x.db",
        "/etc/passwd",
    ],
)
def test_download_path_traversal_returns_400(admin_token, tmp_path, monkeypatch, bad):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.get(
        f"/api/admin/backup/download?filename={bad}",
        headers=_headers(admin_token),
    )
    assert resp.status_code == 400


def test_download_missing_file_returns_404(admin_token, tmp_path, monkeypatch):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(backup_service, "backup_dir", lambda: bdir)

    resp = client.get(
        "/api/admin/backup/download?filename=pc_ops_20260101T000000Z.db",
        headers=_headers(admin_token),
    )
    assert resp.status_code == 404


def test_download_missing_filename_returns_400(admin_token):
    resp = client.get("/api/admin/backup/download", headers=_headers(admin_token))
    assert resp.status_code == 400


# ──────────────────────────────────────────────
# integrity-check (POST /api/backups/integrity-check) + verify_integrity unit
# ──────────────────────────────────────────────


def test_integrity_check_sqlite_ok(admin_token):
    resp = client.post("/api/backups/integrity-check", headers=_headers(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "ok" in data["result"]


def test_verify_integrity_sqlite_branch():
    with app.app_context():
        result = backup_service.verify_integrity()
        assert result["ok"] is True
        assert result["result"][0] == "ok"


def test_verify_integrity_non_sqlite_branch(monkeypatch):
    """Non-sqlite dialect must fall back to a SELECT 1 connectivity probe."""
    with app.app_context():
        monkeypatch.setattr(backup_service, "is_sqlite", lambda: False)
        result = backup_service.verify_integrity()
        assert result["ok"] is True
        assert "sqlite-only" in result["result"][0]


def test_validate_backup_filename_unit():
    """Direct unit coverage of the path-traversal validator."""
    with app.app_context():
        assert (
            backup_service._validate_backup_filename("pc_ops_20260101T000000Z.db")
            == "pc_ops_20260101T000000Z.db"
        )
        for bad in [
            "../../etc/passwd",
            "pc_ops_../x.db",
            "/etc/passwd",
            "pc_ops_x/../y",
            "pre_restore_20260101T000000Z.db",
            "pc_ops_x.txt",
            "",
        ]:
            with pytest.raises(ValueError):
                backup_service._validate_backup_filename(bad)
