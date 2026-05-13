from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import ApiKey

api_keys_bp = Blueprint("api_keys", __name__, url_prefix="/api")


@api_keys_bp.route("/api-keys", methods=["GET"])
@login_required
def list_api_keys():
    keys = ApiKey.query.order_by(ApiKey.created_at.desc()).all()
    return jsonify({"api_keys": [k.to_dict() for k in keys]})


@api_keys_bp.route("/api-keys", methods=["POST"])
@admin_required
def create_api_key():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name は必須です"}), 400
    if len(name) > 200:
        return jsonify({"error": "name は200文字以内で指定してください"}), 400

    key, raw = ApiKey.generate(name)
    db.session.add(key)
    db.session.commit()
    log_operation("create_api_key", f"apikey:{key.id}", f"name={name}")
    result = key.to_dict(include_key=True)
    return jsonify({"message": "API キーを作成しました", "api_key": result}), 201


@api_keys_bp.route("/api-keys/<int:key_id>/rotate", methods=["POST"])
@admin_required
def rotate_api_key(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        return jsonify({"error": f"API キー {key_id} が見つかりません"}), 404

    from secrets import token_urlsafe

    raw = token_urlsafe(32)
    key.key_prefix = raw[:8]
    key.key_value = raw
    db.session.commit()
    log_operation("rotate_api_key", f"apikey:{key_id}", f"name={key.name}")
    result = key.to_dict(include_key=True)
    return jsonify({"message": "API キーをローテートしました", "api_key": result})


@api_keys_bp.route("/api-keys/<int:key_id>", methods=["DELETE"])
@admin_required
def delete_api_key(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        return jsonify({"error": f"API キー {key_id} が見つかりません"}), 404

    db.session.delete(key)
    db.session.commit()
    log_operation("delete_api_key", f"apikey:{key_id}", f"name={key.name}")
    return jsonify({"message": "API キーを削除しました"})
