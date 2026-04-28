from flask import Blueprint, request, jsonify
from extensions import db
from models import User
from auth import (
    hash_password,
    verify_password,
    create_token,
    login_required,
    log_operation,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "ユーザー名とパスワードが必要です"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not verify_password(user.password_hash, password):
        return jsonify({"error": "ユーザー名またはパスワードが正しくありません"}), 401

    if not user.is_active:
        return jsonify({"error": "このアカウントは無効です"}), 403

    token = create_token(user.id, user.username, user.role)

    log_operation("login", f"user:{user.username}", "WebUI login")

    return jsonify(
        {
            "token": token,
            "user": user.to_dict(),
        }
    )


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    return jsonify({"user": request.current_user.to_dict()})


@auth_bp.route("/setup", methods=["POST"])
def setup():
    if User.query.first():
        return jsonify({"error": "既に初期設定済みです"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "username と password は必須です"}), 400
    if len(password) < 8:
        return jsonify({"error": "パスワードは 8 文字以上にしてください"}), 400

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="admin",
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(
        {"message": "管理者ユーザーを作成しました", "user": user.to_dict()}
    ), 201
