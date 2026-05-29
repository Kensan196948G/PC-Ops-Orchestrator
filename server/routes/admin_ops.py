"""Admin operations: DB backup/restore and log tail endpoints.

Phase C-4 (Issue #236) added backup/list/log endpoints. Phase H-3 (Issue #285)
extracted the backup logic into ``backup_service`` (single source of truth) and
added restore + download for disaster-recovery.

Endpoints:
  POST /api/admin/backup/db       — create a DB backup (admin)
  GET  /api/admin/backup/list     — list available backups (admin)
  POST /api/admin/backup/restore  — restore the DB from a backup (admin)
  GET  /api/admin/backup/download — download a backup file (admin)
  GET  /api/admin/logs/app        — tail gunicorn access log (admin)
  GET  /api/admin/logs/error      — tail gunicorn error log (admin)
"""

import os
from collections import deque

from flask import Blueprint, jsonify, request, send_file

import backup_service
from auth import admin_required, log_operation

admin_ops_bp = Blueprint("admin_ops", __name__, url_prefix="/api/admin")

_DEFAULT_LOG_LINES = 100
_MAX_LOG_LINES = 1000

_ACCESS_LOG = os.environ.get("GUNICORN_ACCESS_LOG", "/tmp/pc-ops-access.log")
_ERROR_LOG = os.environ.get("GUNICORN_ERROR_LOG", "/tmp/pc-ops-error.log")


@admin_ops_bp.route("/backup/db", methods=["POST"])
@admin_required
def create_db_backup():
    """Create a DB backup in instance/backups/ with a timestamp filename."""
    try:
        result = backup_service.perform_backup()
    except FileNotFoundError:
        return jsonify({"error": "データベースファイルが見つかりません"}), 404
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501

    log_operation(
        "db_backup_created",
        details=f"file={result['filename']} size={result['size_bytes']}",
    )

    return jsonify(
        {
            "message": "バックアップを作成しました",
            "filename": result["filename"],
            "size_bytes": result["size_bytes"],
            "created_at": result["created_at"],
        }
    ), 201


@admin_ops_bp.route("/backup/list", methods=["GET"])
@admin_required
def list_db_backups():
    """Return a list of available DB backup files."""
    items = backup_service.list_backup_files()
    return jsonify({"backups": items, "total": len(items)})


@admin_ops_bp.route("/backup/restore", methods=["POST"])
@admin_required
def restore_db_backup():
    """Restore the database from a previously created backup (DR)."""
    filename = (request.get_json(silent=True) or {}).get(
        "filename"
    ) or request.args.get("filename")
    if not filename:
        return jsonify({"error": "filename が必要です"}), 400

    try:
        result = backup_service.restore_backup(filename)
    except ValueError:
        return jsonify({"error": "不正なファイル名です"}), 400
    except FileNotFoundError:
        return jsonify({"error": "バックアップが見つかりません"}), 404
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except RuntimeError as exc:
        log_operation(
            "db_backup_restore_failed",
            target=filename,
            details=str(exc),
        )
        return jsonify({"error": "リストア後の整合性検証に失敗しました"}), 500

    log_operation(
        "db_backup_restored",
        target=result["restored_from"],
        details=(
            f"pre_restore={result['pre_restore_backup']} "
            f"integrity_ok={result['integrity_ok']}"
        ),
    )
    return jsonify(
        {
            "message": "リストアが完了しました",
            "restored_from": result["restored_from"],
            "pre_restore_backup": result["pre_restore_backup"],
            "integrity_ok": result["integrity_ok"],
        }
    ), 200


@admin_ops_bp.route("/backup/download", methods=["GET"])
@admin_required
def download_db_backup():
    """Download a backup file (admin). Path-traversal hardened."""
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "filename が必要です"}), 400

    try:
        safe_name = backup_service._validate_backup_filename(filename)
    except ValueError:
        return jsonify({"error": "不正なファイル名です"}), 400

    path = backup_service.backup_dir() / safe_name
    if not path.exists():
        return jsonify({"error": "バックアップが見つかりません"}), 404

    log_operation("db_backup_downloaded", target=safe_name)
    return send_file(str(path), as_attachment=True, download_name=safe_name)


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
