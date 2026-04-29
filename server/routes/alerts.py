import csv
import io
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, make_response
from extensions import db, limiter
from models import PC, Alert
from auth import login_required, require_role
from notify import notify_alert

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/alerts")

_OFFLINE_THRESHOLD_MINUTES = 30
_DISK_LOW_PCT = 10.0
_MEM_HIGH_PCT = 90.0
_HEALTH_CRITICAL = 50.0
_HEALTH_WARNING = 80.0


@alerts_bp.route("", methods=["GET"])
@login_required
def list_alerts():
    severity = request.args.get("severity")
    resolved = request.args.get("resolved", "false").lower() == "true"
    pc_id_raw = request.args.get("pc_id")
    pc_id = int(pc_id_raw) if pc_id_raw is not None else None
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    query = Alert.query.filter_by(resolved=resolved)
    if severity:
        query = query.filter(Alert.severity == severity)
    if pc_id is not None:
        query = query.filter(Alert.pc_id == pc_id)

    severity_order = db.case(
        (Alert.severity == "critical", 0),
        (Alert.severity == "high", 1),
        (Alert.severity == "medium", 2),
        else_=3,
    )
    query = query.order_by(severity_order, Alert.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify(
        {
            "alerts": [a.to_dict() for a in pagination.items],
            "total": pagination.total,
            "page": page,
            "pages": pagination.pages,
            "unresolved_count": Alert.query.filter_by(resolved=False).count(),
        }
    )


@alerts_bp.route("/export.csv", methods=["GET"])
@login_required
def export_alerts_csv():
    severity = request.args.get("severity")
    resolved = request.args.get("resolved", "false").lower() == "true"

    query = Alert.query.filter_by(resolved=resolved)
    if severity:
        query = query.filter(Alert.severity == severity)

    severity_order = db.case(
        (Alert.severity == "critical", 0),
        (Alert.severity == "high", 1),
        (Alert.severity == "medium", 2),
        else_=3,
    )
    alerts = query.order_by(severity_order, Alert.created_at.desc()).limit(5000).all()

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ID",
            "PC名",
            "種別",
            "重大度",
            "メッセージ",
            "解決済み",
            "作成日時",
            "解決日時",
        ]
    )
    for a in alerts:
        pc_name = a.pc.pc_name if a.pc else ""
        writer.writerow(
            [
                a.id,
                pc_name,
                a.alert_type or "",
                a.severity or "",
                a.message or "",
                "はい" if a.resolved else "いいえ",
                a.created_at.isoformat() if a.created_at else "",
                a.resolved_at.isoformat() if a.resolved_at else "",
            ]
        )

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=alerts.csv"
    return response


@alerts_bp.route("/<int:alert_id>", methods=["GET"])
@login_required
def get_alert(alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return jsonify({"error": f"Alert {alert_id} が見つかりません"}), 404
    return jsonify(alert.to_dict())


@alerts_bp.route("/<int:alert_id>/acknowledge", methods=["POST"])
@require_role("admin", "operator")
def acknowledge_alert(alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return jsonify({"error": f"Alert {alert_id} が見つかりません"}), 404
    if alert.resolved:
        return jsonify({"error": "解決済みのアラートは acknowledge できません"}), 400

    alert.acknowledged = True
    alert.acknowledged_by = request.current_user.username
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "acknowledge しました", "alert": alert.to_dict()})


@alerts_bp.route("/<int:alert_id>/resolve", methods=["POST"])
@require_role("admin", "operator")
def resolve_alert(alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return jsonify({"error": f"Alert {alert_id} が見つかりません"}), 404
    if alert.resolved:
        return jsonify({"error": "すでに解決済みです"}), 400

    alert.resolved = True
    alert.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"message": "解決済みにしました", "alert": alert.to_dict()})


@alerts_bp.route("/sync", methods=["POST"])
@limiter.limit("6 per minute")
@require_role("admin", "operator")
def sync_alerts():
    """Generate/update alerts from current PC state (idempotent)."""
    now = datetime.now(timezone.utc)
    offline_threshold = now - timedelta(minutes=_OFFLINE_THRESHOLD_MINUTES)
    pcs = PC.query.all()

    created, resolved_count = 0, 0

    existing_keys: frozenset[str] = frozenset(
        row[0]
        for row in Alert.query.filter_by(resolved=False)
        .with_entities(Alert.source_key)
        .all()
    )

    active_keys: set[str] = set()

    for pc in pcs:
        candidates = _build_candidates(pc, offline_threshold)
        for candidate in candidates:
            active_keys.add(candidate["source_key"])
            if candidate["source_key"] not in existing_keys:
                new_alert = Alert(**candidate)
                db.session.add(new_alert)
                db.session.flush()  # populate id before notify
                notify_alert(new_alert)
                created += 1

    stale = Alert.query.filter(
        Alert.resolved == False,  # noqa: E712
        Alert.source_key.notin_(active_keys) if active_keys else db.true(),
    ).all()
    for alert in stale:
        alert.resolved = True
        alert.resolved_at = now
        resolved_count += 1

    db.session.commit()
    return jsonify(
        {
            "message": "アラート同期完了",
            "created": created,
            "resolved": resolved_count,
            "total_active": Alert.query.filter_by(resolved=False).count(),
        }
    )


def _build_candidates(pc: PC, offline_threshold: datetime) -> list[dict]:
    candidates = []

    last_seen = pc.last_seen
    if last_seen and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen and last_seen < offline_threshold:
        candidates.append(
            {
                "pc_id": pc.id,
                "alert_type": "pc_offline",
                "severity": "high",
                "message": f"{pc.pc_name} が {_OFFLINE_THRESHOLD_MINUTES} 分以上オフラインです",
                "source_key": f"pc_{pc.id}_offline",
            }
        )

    if pc.health_score is not None:
        if pc.health_score < _HEALTH_CRITICAL:
            candidates.append(
                {
                    "pc_id": pc.id,
                    "alert_type": "health_critical",
                    "severity": "critical",
                    "message": f"{pc.pc_name} のヘルススコアが危険域です ({pc.health_score:.1f})",
                    "source_key": f"pc_{pc.id}_health_critical",
                }
            )
        elif pc.health_score < _HEALTH_WARNING:
            candidates.append(
                {
                    "pc_id": pc.id,
                    "alert_type": "health_warning",
                    "severity": "medium",
                    "message": f"{pc.pc_name} のヘルススコアが低下しています ({pc.health_score:.1f})",
                    "source_key": f"pc_{pc.id}_health_warning",
                }
            )

    if pc.disk_total_gb and pc.disk_free_gb is not None and pc.disk_total_gb > 0:
        pct_free = pc.disk_free_gb / pc.disk_total_gb * 100
        if pct_free < _DISK_LOW_PCT:
            candidates.append(
                {
                    "pc_id": pc.id,
                    "alert_type": "disk_low",
                    "severity": "critical",
                    "message": f"{pc.pc_name} のディスク空き容量が {pct_free:.1f}% です",
                    "source_key": f"pc_{pc.id}_disk_low",
                }
            )

    if (
        pc.memory_total_gb
        and pc.memory_available_gb is not None
        and pc.memory_total_gb > 0
    ):
        mem_used_pct = (
            (pc.memory_total_gb - pc.memory_available_gb) / pc.memory_total_gb * 100
        )
        if mem_used_pct > _MEM_HIGH_PCT:
            candidates.append(
                {
                    "pc_id": pc.id,
                    "alert_type": "high_memory",
                    "severity": "high",
                    "message": f"{pc.pc_name} のメモリ使用率が {mem_used_pct:.1f}% です",
                    "source_key": f"pc_{pc.id}_high_memory",
                }
            )

    return candidates
