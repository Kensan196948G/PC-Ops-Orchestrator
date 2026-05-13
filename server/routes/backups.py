import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from auth import admin_required, log_operation, login_required
from extensions import db
from models import BackupJob

backups_bp = Blueprint("backups", __name__, url_prefix="/api")

_STORAGE_PATH = "s3://pc-ops-backups/"


@backups_bp.route("/backups", methods=["GET"])
@login_required
def list_backups():
    jobs = BackupJob.query.order_by(BackupJob.started_at.desc()).limit(30).all()
    total = BackupJob.query.count()
    succeeded = BackupJob.query.filter_by(status="success").count()
    return jsonify(
        {"backups": [j.to_dict() for j in jobs], "total": total, "succeeded": succeeded}
    )


@backups_bp.route("/backups/trigger", methods=["POST"])
@admin_required
def trigger_backup():
    """Simulate an immediate backup job."""
    duration = random.randint(120, 360)
    size = random.randint(500_000_000, 3_000_000_000)
    now = datetime.now(timezone.utc)
    job = BackupJob(
        backup_type="full",
        target="DB + config",
        status="success",
        size_bytes=size,
        duration_seconds=duration,
        storage_path=_STORAGE_PATH,
        started_at=now,
        finished_at=now,
    )
    db.session.add(job)
    db.session.commit()
    log_operation("trigger_backup", f"backup:{job.id}", "manual full backup triggered")
    return jsonify(
        {"message": "バックアップを実行しました", "backup": job.to_dict()}
    ), 201


@backups_bp.route("/backups/integrity-check", methods=["POST"])
@login_required
def integrity_check():
    """Run SQLite PRAGMA integrity_check."""
    try:
        result = db.session.execute(db.text("PRAGMA integrity_check")).fetchall()
        ok = result[0][0] == "ok" if result else False
        return jsonify({"ok": ok, "result": [r[0] for r in result]})
    except Exception as exc:
        return jsonify({"ok": False, "result": [str(exc)]}), 500
