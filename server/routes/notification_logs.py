"""Notification log API — GET /api/notification-logs (Issue #278)."""

import logging

from flask import Blueprint, jsonify, request

from auth import login_required
from extensions import db
from models import AlertRule, NotificationLog

logger = logging.getLogger(__name__)

notification_logs_bp = Blueprint("notification_logs", __name__, url_prefix="/api")

_ALLOWED_STATUSES = frozenset({"sent", "failed", "skipped"})
_ALLOWED_CHANNELS = frozenset({"slack", "teams", "email", "generic_webhook"})


@notification_logs_bp.route("/notification-logs", methods=["GET"])
@login_required
def list_notification_logs():
    """GET /api/notification-logs — paginated list with optional filters."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    rule_id = request.args.get("rule_id", type=int)
    alert_id = request.args.get("alert_id", type=int)
    status = request.args.get("status")
    channel = request.args.get("channel")

    q = NotificationLog.query.order_by(NotificationLog.sent_at.desc())

    if rule_id is not None:
        q = q.filter(NotificationLog.rule_id == rule_id)
    if alert_id is not None:
        q = q.filter(NotificationLog.alert_id == alert_id)
    if status and status in _ALLOWED_STATUSES:
        q = q.filter(NotificationLog.status == status)
    if channel and channel in _ALLOWED_CHANNELS:
        q = q.filter(NotificationLog.channel == channel)

    result = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        {
            "notification_logs": [r.to_dict() for r in result.items],
            "total": result.total,
            "page": page,
            "pages": result.pages,
        }
    )


@notification_logs_bp.route("/notification-logs/<int:log_id>", methods=["GET"])
@login_required
def get_notification_log(log_id):
    """GET /api/notification-logs/<id> — single record."""
    log = db.session.get(NotificationLog, log_id)
    if not log:
        return jsonify({"error": f"通知ログ {log_id} が見つかりません"}), 404
    return jsonify({"notification_log": log.to_dict()})


@notification_logs_bp.route(
    "/alert-rules/<int:rule_id>/notification-logs", methods=["GET"]
)
@login_required
def list_rule_notification_logs(rule_id):
    """GET /api/alert-rules/<id>/notification-logs — logs for a specific rule."""
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    result = (
        NotificationLog.query.filter_by(rule_id=rule_id)
        .order_by(NotificationLog.sent_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    return jsonify(
        {
            "notification_logs": [r.to_dict() for r in result.items],
            "total": result.total,
            "page": page,
            "pages": result.pages,
        }
    )
