from datetime import datetime, timezone

from flask import Blueprint, jsonify

import backup_service
from auth import admin_required, log_operation, login_required
from extensions import db
from models import BackupJob

backups_bp = Blueprint("backups", __name__, url_prefix="/api")


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
    """Run a real DB backup and record the outcome in BackupJob."""
    started = datetime.now(timezone.utc)
    job = BackupJob(
        backup_type="full",
        target="DB + config",
        status="running",
        started_at=started,
    )
    db.session.add(job)
    db.session.commit()

    try:
        result = backup_service.perform_backup()
    except Exception as exc:
        finished = datetime.now(timezone.utc)
        job.status = "failed"
        job.notes = str(exc)
        job.duration_seconds = int((finished - started).total_seconds())
        job.finished_at = finished
        db.session.commit()
        log_operation(
            "trigger_backup",
            f"backup:{job.id}",
            f"manual full backup failed: {exc}",
        )
        return jsonify(
            {"error": "バックアップに失敗しました", "backup": job.to_dict()}
        ), 500

    finished = datetime.now(timezone.utc)
    job.status = "success"
    job.size_bytes = result["size_bytes"]
    job.duration_seconds = int((finished - started).total_seconds())
    job.storage_path = result["path"]
    job.finished_at = finished
    db.session.commit()
    log_operation(
        "trigger_backup",
        f"backup:{job.id}",
        f"manual full backup created: {result['filename']}",
    )
    return jsonify(
        {"message": "バックアップを実行しました", "backup": job.to_dict()}
    ), 201


@backups_bp.route("/backups/integrity-check", methods=["POST"])
@login_required
def integrity_check():
    """Run a dialect-aware database integrity check."""
    try:
        result = backup_service.verify_integrity()
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "result": [str(exc)]}), 500
