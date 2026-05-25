"""Collection Policy CRUD API (Issue #248)."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import login_required
from extensions import db
from models import PC, CollectionPolicy, PCGroup

bp = Blueprint("collection_policies", __name__, url_prefix="/api/collection-policies")

VALID_METRIC_TYPES = set(CollectionPolicy.METRIC_TYPES)


def _validate_payload(data: dict) -> tuple[dict, int] | None:
    """Return error response tuple if payload is invalid, else None."""
    metric_type = data.get("metric_type")
    if metric_type and metric_type not in VALID_METRIC_TYPES:
        return (
            jsonify(
                {
                    "error": f"Invalid metric_type. Must be one of: {sorted(VALID_METRIC_TYPES)}"
                }
            ),
            400,
        )
    freq = data.get("frequency_minutes")
    if freq is not None and (not isinstance(freq, int) or freq < 1):
        return jsonify({"error": "frequency_minutes must be a positive integer"}), 400
    return None


@bp.get("")
@login_required
def list_policies():
    """List all collection policies (global + group-specific)."""
    metric_type = request.args.get("metric_type")
    group_id = request.args.get("group_id", type=int)

    q = CollectionPolicy.query
    if metric_type:
        q = q.filter_by(metric_type=metric_type)
    if group_id is not None:
        q = q.filter_by(group_id=group_id)

    policies = q.order_by(
        CollectionPolicy.group_id.nullsfirst(), CollectionPolicy.metric_type
    ).all()
    return jsonify([p.to_dict() for p in policies]), 200


@bp.post("")
@login_required
def create_policy():
    """Create a new collection policy."""
    data = request.get_json(silent=True) or {}

    metric_type = data.get("metric_type")
    if not metric_type:
        return jsonify({"error": "metric_type is required"}), 400

    err = _validate_payload(data)
    if err:
        return err

    group_id = data.get("group_id")
    if group_id is not None:
        if not PCGroup.query.get(group_id):
            return jsonify({"error": f"PCGroup {group_id} not found"}), 404

    # Enforce unique constraint (group_id, metric_type)
    existing = CollectionPolicy.query.filter_by(
        group_id=group_id, metric_type=metric_type
    ).first()
    if existing:
        return (
            jsonify(
                {
                    "error": "Policy already exists for this group/metric combination",
                    "existing_id": existing.id,
                }
            ),
            409,
        )

    now = datetime.now(timezone.utc)
    policy = CollectionPolicy(
        group_id=group_id,
        metric_type=metric_type,
        frequency_minutes=data.get("frequency_minutes", 60),
        is_enabled=data.get("is_enabled", True),
        created_at=now,
        updated_at=now,
    )
    db.session.add(policy)
    db.session.commit()
    return jsonify(policy.to_dict()), 201


@bp.get("/<int:policy_id>")
@login_required
def get_policy(policy_id: int):
    """Get a single collection policy by ID."""
    policy = CollectionPolicy.query.get_or_404(policy_id)
    return jsonify(policy.to_dict()), 200


@bp.put("/<int:policy_id>")
@login_required
def update_policy(policy_id: int):
    """Update an existing collection policy."""
    policy = CollectionPolicy.query.get_or_404(policy_id)
    data = request.get_json(silent=True) or {}

    err = _validate_payload(data)
    if err:
        return err

    if "metric_type" in data:
        new_metric = data["metric_type"]
        if new_metric != policy.metric_type:
            conflict = CollectionPolicy.query.filter_by(
                group_id=policy.group_id, metric_type=new_metric
            ).first()
            if conflict and conflict.id != policy_id:
                return jsonify(
                    {"error": "Another policy already uses that group/metric pair"}
                ), 409
        policy.metric_type = new_metric

    if "frequency_minutes" in data:
        policy.frequency_minutes = data["frequency_minutes"]
    if "is_enabled" in data:
        policy.is_enabled = bool(data["is_enabled"])
    if "group_id" in data:
        new_gid = data["group_id"]
        if new_gid is not None and not PCGroup.query.get(new_gid):
            return jsonify({"error": f"PCGroup {new_gid} not found"}), 404
        policy.group_id = new_gid

    policy.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(policy.to_dict()), 200


@bp.delete("/<int:policy_id>")
@login_required
def delete_policy(policy_id: int):
    """Delete a collection policy."""
    policy = CollectionPolicy.query.get_or_404(policy_id)
    db.session.delete(policy)
    db.session.commit()
    return jsonify({"message": f"Policy {policy_id} deleted"}), 200


@bp.get("/effective/<int:pc_id>")
@login_required
def effective_policy(pc_id: int):
    """Return effective policies for a specific PC (group overrides global)."""
    pc = PC.query.get_or_404(pc_id)

    # Collect group IDs for this PC
    group_ids = [g.id for g in pc.groups]

    effective: dict[str, dict] = {}
    for metric in CollectionPolicy.METRIC_TYPES:
        # Group-level policy wins over global
        policy = None
        if group_ids:
            policy = (
                CollectionPolicy.query.filter(
                    CollectionPolicy.group_id.in_(group_ids),
                    CollectionPolicy.metric_type == metric,
                )
                .order_by(CollectionPolicy.group_id)
                .first()
            )
        if policy is None:
            policy = CollectionPolicy.query.filter_by(
                group_id=None, metric_type=metric
            ).first()

        effective[metric] = (
            policy.to_dict()
            if policy
            else {
                "metric_type": metric,
                "frequency_minutes": 60,
                "is_enabled": True,
                "source": "default",
            }
        )

    return (
        jsonify(
            {
                "pc_id": pc_id,
                "pc_name": pc.pc_name,
                "group_ids": group_ids,
                "effective_policies": effective,
            }
        ),
        200,
    )
