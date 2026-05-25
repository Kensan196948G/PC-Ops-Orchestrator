import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db, limiter
from models import Alert, AlertRule, PC, SystemSnapshot
from notify import ALLOWED_CHANNEL_TYPES, dispatch_via_rule

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

    raw_channel = data.get("channel_type")
    if raw_channel is not None and raw_channel != "":
        if not isinstance(raw_channel, str):
            return None, "channel_type は文字列で指定してください"
        channel_type = raw_channel.strip()
        if channel_type not in ALLOWED_CHANNEL_TYPES:
            return (
                None,
                f"channel_type は {sorted(ALLOWED_CHANNEL_TYPES)} のいずれかで指定してください",
            )
    else:
        channel_type = None

    return {
        "name": name,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
        "severity": severity,
        "notify_email": (data.get("notify_email") or "").strip() or None,
        "notify_slack_webhook": (data.get("notify_slack_webhook") or "").strip()
        or None,
        "notify_teams_webhook": (data.get("notify_teams_webhook") or "").strip()
        or None,
        "notify_webhook_url": (data.get("notify_webhook_url") or "").strip() or None,
        "channel_type": channel_type,
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


class _TestAlert:
    """Synthetic alert object passed to notify.dispatch_via_rule for /test-notify."""

    def __init__(self, rule: AlertRule):
        self.id = 0
        self.alert_type = "test_notification"
        self.severity = rule.severity or "warning"
        self.message = f"[テスト通知] ルール「{rule.name}」の通知テストです"
        self.pc_id = None
        self.source_key = f"test:rule:{rule.id}"
        self.created_at = datetime.now(timezone.utc)


@alert_rules_bp.route("/alert-rules/<int:rule_id>/test-notify", methods=["POST"])
@limiter.limit("6 per minute")
@admin_required
def test_notify(rule_id):
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404

    test_alert = _TestAlert(rule)
    sent = dispatch_via_rule(test_alert, rule)

    # Translate per-channel booleans into a UI-friendly status map for every
    # known channel, so the front-end always knows what was attempted.
    #   sent[channel] = True/False  → "sent" / "failed"
    #   target が空                  → "not_configured" (この通知先は未登録)
    #   target はあるが今回は送らない → "skipped" (例: channel_type で限定された)
    results = {}
    rule_targets = {
        "slack": rule.notify_slack_webhook,
        "teams": rule.notify_teams_webhook,
        "generic_webhook": rule.notify_webhook_url,
        "email": rule.notify_email,
    }
    for channel, target in rule_targets.items():
        if channel in sent:
            results[channel] = "sent" if sent[channel] else "failed"
        elif not target:
            results[channel] = "not_configured"
        else:
            results[channel] = "skipped"

    log_operation(
        "test_notify_alert_rule",
        f"rule:{rule_id}",
        f"channel_type={rule.channel_type or 'auto'} results={results}",
    )

    return jsonify({"message": "テスト通知を送信しました", "results": results})


@alert_rules_bp.route("/alert-rules/<int:rule_id>/evaluate", methods=["POST"])
@limiter.limit("30 per minute")
@admin_required
def evaluate_alert_rule(rule_id):
    """POST /api/alert-rules/<id>/evaluate — immediately evaluate one rule against all PCs."""
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return jsonify({"error": f"アラートルール {rule_id} が見つかりません"}), 404

    from scheduler import _OPERATOR_FNS, _OFFLINE_THRESHOLD_MINUTES, _get_metric_value

    pcs = PC.query.all()
    created = 0
    for pc in pcs:
        fn = _OPERATOR_FNS.get(rule.operator)
        if fn is None:
            continue
        value = _get_metric_value(pc, rule.metric, SystemSnapshot)
        if value is None:
            continue
        threshold = (
            rule.threshold if rule.threshold is not None else _OFFLINE_THRESHOLD_MINUTES
        )
        if not fn(value, threshold):
            continue
        source_key = f"rule:{rule.id}:pc:{pc.id}"
        if Alert.query.filter_by(source_key=source_key, resolved=False).first():
            continue
        db.session.add(
            Alert(
                pc_id=pc.id,
                alert_rule_id=rule.id,
                alert_type=f"rule_{rule.metric}",
                severity=rule.severity or "warning",
                message=(
                    f"[手動評価] {pc.pc_name}: {rule.metric} "
                    f"{rule.operator} {threshold} (現在値: {round(value, 2)})"
                ),
                source_key=source_key,
            )
        )
        created += 1
    if created:
        db.session.commit()

    log_operation(
        "evaluate_alert_rule",
        f"rule:{rule_id}",
        f"alerts_created={created}",
    )
    return jsonify({"rule_id": rule_id, "alerts_created": created})
