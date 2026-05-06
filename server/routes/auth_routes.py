import re
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from extensions import db, limiter
from models import User
from auth import (
    ALLOWED_ROLES,
    hash_password,
    verify_password,
    create_token,
    login_required,
    admin_required,
    log_operation,
)

_MAX_FAILED_LOGINS = 5
_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z\d]).{8,}$")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")

    if not username or not password:
        return jsonify({"error": "ユーザー名とパスワードが必要です"}), 400

    user = User.query.filter_by(username=username).first()

    if not user or not verify_password(user.password_hash, password):
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= _MAX_FAILED_LOGINS and not user.is_locked:
                user.is_locked = True
                user.locked_at = datetime.now(timezone.utc)
            db.session.commit()
        return jsonify({"error": "ユーザー名またはパスワードが正しくありません"}), 401

    if not user.is_active:
        return jsonify({"error": "このアカウントは無効です"}), 403

    if user.is_locked:
        return jsonify(
            {"error": "アカウントがロックされています。管理者にお問い合わせください"}
        ), 403

    user.last_login = datetime.now(timezone.utc)
    user.failed_login_count = 0
    db.session.commit()

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
@limiter.limit("3 per minute")
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
        failed_login_count=0,
        is_locked=False,
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(
        {"message": "管理者ユーザーを作成しました", "user": user.to_dict()}
    ), 201


@auth_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.asc()).all()
    return jsonify({"users": [u.to_dict() for u in users], "total": len(users)})


@auth_bp.route("/users", methods=["POST"])
@limiter.limit("10 per minute")
@admin_required
def create_user():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")
    raw_role = data.get("role", "viewer")
    if not isinstance(raw_role, str):
        return jsonify({"error": "role は文字列で指定してください"}), 400
    role = raw_role.strip()

    if not username or not password:
        return jsonify({"error": "username と password は必須です"}), 400
    if not _PASSWORD_RE.match(password):
        return jsonify(
            {
                "error": "パスワードは 8 文字以上で大小英字・数字・記号をそれぞれ含む必要があります"
            }
        ), 400
    if role not in ALLOWED_ROLES:
        return jsonify(
            {
                "error": (
                    "role は次のいずれかを指定してください: "
                    + ", ".join(sorted(ALLOWED_ROLES))
                )
            }
        ), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "そのユーザー名は既に使用されています"}), 409

    user = User(username=username, password_hash=hash_password(password), role=role)
    db.session.add(user)
    db.session.commit()
    log_operation("create_user", f"user:{username}", f"ユーザー作成 role={role}")
    return jsonify({"message": "ユーザーを作成しました", "user": user.to_dict()}), 201


@auth_bp.route("/users/<int:user_id>", methods=["PATCH"])
@admin_required
def update_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": f"ユーザー {user_id} が見つかりません"}), 404

    if target.id == request.current_user.id:
        return jsonify({"error": "自分自身は変更できません"}), 400

    data = request.get_json() or {}
    if "role" in data:
        raw_role = data["role"]
        if not isinstance(raw_role, str) or raw_role.strip() not in ALLOWED_ROLES:
            return jsonify(
                {
                    "error": (
                        "role は次のいずれかを指定してください: "
                        + ", ".join(sorted(ALLOWED_ROLES))
                    )
                }
            ), 400
        target.role = raw_role.strip()
    if "is_active" in data:
        target.is_active = bool(data["is_active"])
    if "password" in data:
        if not _PASSWORD_RE.match(data["password"]):
            return jsonify(
                {
                    "error": "パスワードは 8 文字以上で大小英字・数字・記号をそれぞれ含む必要があります"
                }
            ), 400
        target.password_hash = hash_password(data["password"])

    db.session.commit()
    log_operation("update_user", f"user:{target.username}", "ユーザー情報更新")
    return jsonify({"message": "ユーザーを更新しました", "user": target.to_dict()})


@auth_bp.route("/users/<int:user_id>/unlock", methods=["POST"])
@admin_required
def unlock_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": f"ユーザー {user_id} が見つかりません"}), 404

    target.is_locked = False
    target.failed_login_count = 0
    target.locked_at = None
    db.session.commit()
    log_operation("unlock_user", f"user:{target.username}", "アカウントロック解除")
    return jsonify(
        {
            "message": f"ユーザー {target.username} のロックを解除しました",
            "user": target.to_dict(),
        }
    )


@auth_bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": f"ユーザー {user_id} が見つかりません"}), 404

    if target.id == request.current_user.id:
        return jsonify({"error": "自分自身は削除できません"}), 400

    username = target.username
    db.session.delete(target)
    db.session.commit()
    log_operation("delete_user", f"user:{username}", "ユーザー削除")
    return jsonify({"message": f"ユーザー {username} を削除しました"})
