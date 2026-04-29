from datetime import datetime, timezone, timedelta
from functools import wraps
import hmac

import jwt
from flask import request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from models import User, OperationLog
from extensions import db

ALLOWED_ROLES: frozenset[str] = frozenset({"admin", "operator", "viewer"})


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def create_token(user_id, username, role):
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_token(token):
    try:
        payload = jwt.decode(
            token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return jsonify({"error": "認証トークンが必要です"}), 401

        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "トークンが無効または期限切れです"}), 401

        user = db.session.get(User, int(payload["sub"]))
        if not user or not user.is_active:
            return jsonify({"error": "ユーザーが見つからないか無効です"}), 401

        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def require_role(*roles):
    """Restrict access to users whose role is one of the given values.

    Always implies login_required: callers do not need to stack both decorators.
    Returns 401 when unauthenticated, 403 when authenticated but lacking role.
    """
    allowed = set(roles) or {"admin"}
    invalid = allowed - ALLOWED_ROLES
    if invalid:
        raise ValueError(f"unknown role(s): {sorted(invalid)}")

    def wrapper(f):
        @login_required
        @wraps(f)
        def decorated(*args, **kwargs):
            user_role = getattr(request.current_user, "role", None)
            if user_role not in allowed:
                return jsonify(
                    {
                        "error": (
                            "この操作には次のいずれかの権限が必要です: "
                            + ", ".join(sorted(allowed))
                        )
                    }
                ), 403
            return f(*args, **kwargs)

        return decorated

    return wrapper


def admin_required(f):
    """Backward-compatible alias for ``@require_role("admin")``."""
    return require_role("admin")(f)


def agent_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return jsonify({"error": "Agentトークンが必要です"}), 401

        valid_keys = current_app.config.get("AGENT_API_KEYS", [])
        if not any(hmac.compare_digest(token, key) for key in valid_keys):
            return jsonify({"error": "無効なAgentトークンです"}), 401

        return f(*args, **kwargs)

    return decorated


def log_operation(action, target=None, details=None):
    if hasattr(request, "current_user") and request.current_user is not None:
        user = request.current_user
        created_by = f"{user.username}[{user.role}]"
    else:
        created_by = "system"

    op = OperationLog(
        action=action,
        target=target,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else None,
        created_by=created_by,
    )
    db.session.add(op)
    db.session.commit()
