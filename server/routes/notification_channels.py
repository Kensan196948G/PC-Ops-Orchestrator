from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import NotificationChannel

notification_channels_bp = Blueprint(
    "notification_channels", __name__, url_prefix="/api"
)

_VALID_CHANNEL_TYPES = frozenset({"slack", "teams", "email", "webhook"})


@notification_channels_bp.route("/notification-channels", methods=["GET"])
@login_required
def list_notification_channels():
    channels = NotificationChannel.query.order_by(NotificationChannel.name).all()
    return jsonify({"channels": [c.to_dict() for c in channels]})


@notification_channels_bp.route("/notification-channels", methods=["POST"])
@admin_required
def create_notification_channel():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name は必須です"}), 400
    if len(name) > 100:
        return jsonify({"error": "name は100文字以内で指定してください"}), 400

    channel_type = (data.get("channel_type") or "").strip()
    if not channel_type:
        return jsonify({"error": "channel_type は必須です"}), 400
    if channel_type not in _VALID_CHANNEL_TYPES:
        return jsonify(
            {
                "error": f"channel_type は {sorted(_VALID_CHANNEL_TYPES)} のいずれかで指定してください"
            }
        ), 400

    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"error": "target は必須です"}), 400
    if len(target) > 500:
        return jsonify({"error": "target は500文字以内で指定してください"}), 400

    if NotificationChannel.query.filter_by(name=name).first():
        return jsonify({"error": f"チャンネル '{name}' は既に存在します"}), 409

    channel = NotificationChannel(
        name=name,
        channel_type=channel_type,
        target=target,
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(channel)
    db.session.commit()

    log_operation(
        "create_notification_channel",
        f"channel:{channel.id}",
        f"name={channel.name} type={channel.channel_type}",
    )
    return jsonify(
        {"message": "通知チャンネルを作成しました", "channel": channel.to_dict()}
    ), 201


@notification_channels_bp.route(
    "/notification-channels/<int:channel_id>", methods=["PUT"]
)
@admin_required
def update_notification_channel(channel_id):
    channel = db.session.get(NotificationChannel, channel_id)
    if not channel:
        return jsonify({"error": f"通知チャンネル {channel_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"error": "name は必須です"}), 400
        if len(name) > 100:
            return jsonify({"error": "name は100文字以内で指定してください"}), 400
        existing = NotificationChannel.query.filter_by(name=name).first()
        if existing and existing.id != channel_id:
            return jsonify({"error": f"チャンネル '{name}' は既に存在します"}), 409
        channel.name = name

    if "channel_type" in data:
        channel_type = (data["channel_type"] or "").strip()
        if channel_type not in _VALID_CHANNEL_TYPES:
            return jsonify(
                {
                    "error": f"channel_type は {sorted(_VALID_CHANNEL_TYPES)} のいずれかで指定してください"
                }
            ), 400
        channel.channel_type = channel_type

    if "target" in data:
        target = (data["target"] or "").strip()
        if not target:
            return jsonify({"error": "target は必須です"}), 400
        if len(target) > 500:
            return jsonify({"error": "target は500文字以内で指定してください"}), 400
        channel.target = target

    if "is_active" in data:
        channel.is_active = bool(data["is_active"])

    db.session.commit()

    log_operation(
        "update_notification_channel",
        f"channel:{channel_id}",
        f"name={channel.name}",
    )
    return jsonify(
        {"message": "通知チャンネルを更新しました", "channel": channel.to_dict()}
    )


@notification_channels_bp.route(
    "/notification-channels/<int:channel_id>", methods=["DELETE"]
)
@admin_required
def delete_notification_channel(channel_id):
    channel = db.session.get(NotificationChannel, channel_id)
    if not channel:
        return jsonify({"error": f"通知チャンネル {channel_id} が見つかりません"}), 404

    db.session.delete(channel)
    db.session.commit()

    log_operation(
        "delete_notification_channel", f"channel:{channel_id}", "通知チャンネル削除"
    )
    return jsonify({"message": "通知チャンネルを削除しました"})
