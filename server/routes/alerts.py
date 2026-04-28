from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from extensions import db
from models import PC, Alert
from auth import login_required

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
    pc_id = request.args.get("pc_id", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    query = Alert.query.filter_by(resolved=resolved)
    if severity:
        query = query.filter(Alert.severity == severity)
    if pc_id:
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


@alerts_bp.route("/<int:alert_id>", methods=["GET"])
@login_required
def get_alert(alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return jsonify({"error": f"Alert {alert_id} が見つかりません"}), 404
    return jsonify(alert.to_dict())


@alerts_bp.route("/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
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
@login_required
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
@login_required
def sync_alerts():
    """Generate/update alerts from current PC state (idempotent)."""
    now = datetime.now(timezone.utc)
    offline_threshold = now - timedelta(minutes=_OFFLINE_THRESHOLD_MINUTES)
    pcs = PC.query.all()

    created, resolved = 0, 0

    active_keys: set[str] = set()

    for pc in pcs:
        candidates = _build_candidates(pc, offline_threshold)
        for candidate in candidates:
            active_keys.add(candidate["source_key"])
            existing = Alert.query.filter_by(
                source_key=candidate["source_key"], resolved=False
            ).first()
            if not existing:
                db.session.add(Alert(**candidate))
                created += 1

    stale = Alert.query.filter(
        Alert.resolved == False,  # noqa: E712
        Alert.source_key.notin_(active_keys) if active_keys else db.true(),
    ).all()
    for alert in stale:
        alert.resolved = True
        alert.resolved_at = now
        resolved += 1

    db.session.commit()
    return jsonify(
        {
            "message": "アラート同期完了",
            "created": created,
            "resolved": resolved,
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
