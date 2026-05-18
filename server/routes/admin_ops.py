"""Admin operations: DB backup and log tail endpoints (Phase C-4, Issue #236).

Endpoints:
  POST /api/admin/backup/db    — copy SQLite DB to instance/backups/ (admin)
  GET  /api/admin/backup/list  — list available backups (admin)
  GET  /api/admin/logs/app     — tail gunicorn access log (admin)
  GET  /api/admin/logs/error   — tail gunicorn error log (admin)
"""

import os
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from auth import admin_required, log_operation

admin_ops_bp = Blueprint("admin_ops", __name__, url_prefix="/api/admin")

_MAX_BACKUP_COUNT = 10
_DEFAULT_LOG_LINES = 100
_MAX_LOG_LINES = 1000

_ACCESS_LOG = os.environ.get("GUNICORN_ACCESS_LOG", "/tmp/pc-ops-access.log")
_ERROR_LOG = os.environ.get("GUNICORN_ERROR_LOG", "/tmp/pc-ops-error.log")


def _backup_dir() -> Path:
    instance_path = Path(current_app.instance_path)
    bdir = instance_path / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


def _db_path() -> Path:
    db_url: str = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if db_url.startswith("sqlite:///"):
        rel = db_url[len("sqlite:///") :]
        if rel == ":memory:" or not rel:
            return Path(current_app.instance_path) / "pc_ops.db"
        p = Path(rel)
        if not p.is_absolute():
            p = Path(current_app.instance_path) / p
        return p
    return Path(current_app.instance_path) / "pc_ops.db"


@admin_ops_bp.route("/backup/db", methods=["POST"])
@admin_required
def create_db_backup():
    """Copy the SQLite database to instance/backups/ with a timestamp filename."""
    src = _db_path()
    if not src.exists():
        return jsonify({"error": "データベースファイルが見つかりません"}), 404

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = _backup_dir() / f"pc_ops_{ts}.db"

    # sqlite3.backup is safe under concurrent reads/writes (WAL-aware)
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    size_bytes = dest.stat().st_size

    # Rotate: keep only the _MAX_BACKUP_COUNT newest files
    backups = sorted(_backup_dir().glob("pc_ops_*.db"), key=lambda f: f.stat().st_mtime)
    while len(backups) > _MAX_BACKUP_COUNT:
        backups.pop(0).unlink(missing_ok=True)

    log_operation("db_backup_created", details=f"file={dest.name} size={size_bytes}")

    return jsonify(
        {
            "message": "バックアップを作成しました",
            "filename": dest.name,
            "size_bytes": size_bytes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ), 201


@admin_ops_bp.route("/backup/list", methods=["GET"])
@admin_required
def list_db_backups():
    """Return a list of available DB backup files."""
    bdir = _backup_dir()
    files = sorted(
        bdir.glob("pc_ops_*.db"), key=lambda f: f.stat().st_mtime, reverse=True
    )
    items = [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        for f in files
    ]
    return jsonify({"backups": items, "total": len(items)})


def _tail_file(path: str, n: int) -> list[str]:
    """Return the last *n* lines of a text file without loading it all into memory."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return list(deque(fh, maxlen=n))
    except FileNotFoundError:
        return []


@admin_ops_bp.route("/logs/app", methods=["GET"])
@admin_required
def get_app_log():
    """Return the last N lines of the gunicorn access log."""
    n = min(int(request.args.get("lines", _DEFAULT_LOG_LINES)), _MAX_LOG_LINES)
    lines = _tail_file(_ACCESS_LOG, n)
    return jsonify({"log_file": _ACCESS_LOG, "lines": lines, "count": len(lines)})


@admin_ops_bp.route("/logs/error", methods=["GET"])
@admin_required
def get_error_log():
    """Return the last N lines of the gunicorn error log."""
    n = min(int(request.args.get("lines", _DEFAULT_LOG_LINES)), _MAX_LOG_LINES)
    lines = _tail_file(_ERROR_LOG, n)
    return jsonify({"log_file": _ERROR_LOG, "lines": lines, "count": len(lines)})
