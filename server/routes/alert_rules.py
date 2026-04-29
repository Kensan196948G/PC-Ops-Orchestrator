import json
import logging
import urllib.request
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import AlertRule

logger = logging.getLogger(__name__)

alert_rules_bp = Blueprint("alert_rules", __name__, url_prefix="/api")

_ALLOWED_METRICS = frozenset({"cpu", "memory", "disk", "offline"})
_ALLOWED_OPERATORS = frozenset({"gt", "lt", "gte", "lte"})
_ALLOWED_SEVERITIES = frozenset({"warning", "critical"})


def _validate_rule(data):
    name = (data.get("name") or "").strip()
    if not name:
        return None, "name は必須です"
    if len(name) > 255:
        return None, "name は255文字以内で指定してください"

    metric = (data.get("metric") or "").strip()
    if metric not in _ALLOWED_METRICS:
        return (
            None,
            f"metric は {sorted(_ALLOWED_METRICS)} のいずれかで指定してください",
        )

    operator = (data.get("operator") or "gt").strip()
    if operator not in _ALLOWED_OPERATORS:
        return (
            None,
            f"operator は {sorted(_ALLOWED_OPERATORS)} のいずれかで指定してください",
        )

    severity = (data.get("severity") or "warning").strip()
    if severity not in _ALLOWED_SEVERITIES:
        return (
            None,
            f"severity は {sorted(_ALLOWED_SEVERITIES)} のいずれかで指定してください",
        )

    threshold = data.get("threshold")
    if metric != "offline":
        if threshold is None:
            return None, "threshold は必須です（offline 以外）"
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return None, "threshold は数値で指定してください"
        if threshold < 0 or threshold > 100:
            return None, "threshold は 0〜100 の範囲で指定してください"

    return {
        "name": name,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "notify_email": (data.get("notify_email") or "").strip() or None,
        "notify_slack_webhook": (data.get("notify_slack_webhook") or "").strip()
        or None,
        "is_enabled": bool(data.get("is_enabled", True)),
    }, None


@alert_rules_bp.route("/alert-rules", methods=["GET"])
@login_required
def list_alert_rules():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    q = AlertRule.query.order_by(AlertRule.id)
    result = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        {
            "alert_rules": [r.to_dict() for r in result.items],
            "total": result.total,
            "page": page,
            "pages": result.pages,
        }
    )


@alert_rules_bp.route("/alert-rules", methods=["POST"])
@admin_required
def create_alert_rule():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    fields, err = _validate_rule(data)
    if err:
        return jsonify({"error": err}), 400

    rule = AlertRule(created_by=request.current_user.username, **fields)
    db.session.add(rule)
    db.session.commit()
    log_operation(
        "create_alert_rule",
        f"rule:{rule.id}",
        json.dumps({"name": rule.name, "metric": rule.metric}, ensure_ascii=False),
    )
    return jsonify(
        {"message": "アラートルールを作成しました", "alert_rule": rule.to_dict()}
    ), 201


@alert_rules_bp.route("/alert-rules/<int:rule_id>", methods=["GET"])
@login_required
def get_alert_rule(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404
    return jsonify({"alert_rule": rule.to_dict()})


@alert_rules_bp.route("/alert-rules/<int:rule_id>", methods=["PUT"])
@admin_required
def update_alert_rule(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    fields, err = _validate_rule(data)
    if err:
        return jsonify({"error": err}), 400

    for k, v in fields.items():
        setattr(rule, k, v)
    rule.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    log_operation(
        "update_alert_rule",
        f"rule:{rule_id}",
        json.dumps({"name": rule.name}, ensure_ascii=False),
    )
    return jsonify(
        {"message": "アラートルールを更新しました", "alert_rule": rule.to_dict()}
    )


@alert_rules_bp.route("/alert-rules/<int:rule_id>", methods=["DELETE"])
@admin_required
def delete_alert_rule(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404
    db.session.delete(rule)
    db.session.commit()
    log_operation("delete_alert_rule", f"rule:{rule_id}", "アラートルール削除")
    return jsonify({"message": "アラートルールを削除しました"})


@alert_rules_bp.route("/alert-rules/<int:rule_id>/toggle", methods=["POST"])
@admin_required
def toggle_alert_rule(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404
    rule.is_enabled = not rule.is_enabled
    rule.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    state = "有効" if rule.is_enabled else "無効"
    return jsonify(
        {"message": f"アラートルールを{state}にしました", "alert_rule": rule.to_dict()}
    )


def _send_slack(webhook_url: str, text: str) -> bool:
    try:
        payload = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc)
        return False


@alert_rules_bp.route("/alert-rules/<int:rule_id>/test-notify", methods=["POST"])
@admin_required
def test_notify(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404

    results = {}
    msg = f"[テスト通知] ルール「{rule.name}」の通知テストです"

    if rule.notify_slack_webhook:
        ok = _send_slack(rule.notify_slack_webhook, msg)
        results["slack"] = "sent" if ok else "failed"
    else:
        results["slack"] = "skipped"

    results["email"] = "skipped"

    return jsonify({"message": "テスト通知を送信しました", "results": results})
