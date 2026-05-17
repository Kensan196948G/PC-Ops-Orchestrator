"""Phase B-3 (#218) — Immutable audit log chain + before/after diff tests.

Covers:
- SHA-256 chain hash is computed and stored on each log_operation() call
- Chain hash is deterministic: prev_hash | action | target | created_at (naive UTC)
- before= / after= kwargs are stored in previous_value / new_value
- GET /api/audit/logs/verify returns ok=True when chain is intact
- GET /api/audit/logs/verify returns violations when a hash is corrupted
- Verify endpoint is admin-only (403 for viewer)
- Legacy logs with log_hash=None are skipped without error
"""

import hashlib
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import OperationLog, User

app = create_app("testing")
client = app.test_client()

_unique = uuid.uuid4().hex[:8]
_admin_token = None
_viewer_token = None

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def setup_module():
    global _admin_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, pw in [
            (f"al_admin_{_unique}", "admin", "AdminAl1!"),
            (f"al_viewer_{_unique}", "viewer", "ViewAl1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(username=username, password_hash=hash_password(pw), role=role)
                )
        db.session.commit()
    _admin_token = _login(f"al_admin_{_unique}", "AdminAl1!")
    _viewer_token = _login(f"al_viewer_{_unique}", "ViewAl1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _trigger_log(action="test_action", target="test_target", before=None, after=None):
    """Insert an audit log via log_operation inside a fake request context."""
    from auth import log_operation

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        with app.app_context():
            db.session.expire_all()
            log_operation(
                action, target=target, details="test", before=before, after=after
            )


# ---------------------------------------------------------------------------
# Tests: hash computation
# ---------------------------------------------------------------------------


def test_log_hash_is_set():
    """log_operation stores a non-empty sha256 log_hash."""
    with app.app_context():
        _trigger_log("hash_test_action", "hash_test_target")
        log = OperationLog.query.filter_by(action="hash_test_action").first()
        assert log is not None
        assert log.log_hash is not None
        assert len(log.log_hash) == 64


def test_log_hash_chain_integrity():
    """Two consecutive logs form a valid chain: log2.log_hash uses log1 as prev_hash."""
    tag = uuid.uuid4().hex[:6]
    a1 = f"chain_a1_{tag}"
    a2 = f"chain_a2_{tag}"

    _trigger_log(a1, "chain_target_1")
    _trigger_log(a2, "chain_target_2")

    with app.app_context():
        log1 = OperationLog.query.filter_by(action=a1).first()
        log2 = OperationLog.query.filter_by(action=a2).first()
        assert log1 is not None and log2 is not None
        assert log1.id < log2.id

        # log2's prev_hash is the actual last log before log2 was inserted.
        # Find the log immediately before log2 to get its hash.
        prev_of_log2 = (
            db.session.query(OperationLog)
            .filter(OperationLog.id < log2.id)
            .order_by(OperationLog.id.desc())
            .first()
        )
        actual_prev_hash = (
            prev_of_log2.log_hash if (prev_of_log2 and prev_of_log2.log_hash) else ""
        )

        expected = hashlib.sha256(
            f"{actual_prev_hash}|{log2.action}|{log2.target or ''}|"
            f"{log2.created_at.strftime(_TS_FMT)}".encode()
        ).hexdigest()
        assert log2.log_hash == expected


def test_before_after_stored():
    """before= / after= kwargs are stored in previous_value / new_value."""
    with app.app_context():
        _trigger_log(
            "diff_action",
            "diff_target",
            before='{"status":"offline"}',
            after='{"status":"online"}',
        )
        log = OperationLog.query.filter_by(action="diff_action").first()
        assert log is not None
        assert log.previous_value == '{"status":"offline"}'
        assert log.new_value == '{"status":"online"}'


def test_before_after_none_by_default():
    """Without before/after kwargs, previous_value/new_value are None."""
    with app.app_context():
        _trigger_log("no_diff_action", "no_diff_target")
        log = OperationLog.query.filter_by(action="no_diff_action").first()
        assert log is not None
        assert log.previous_value is None
        assert log.new_value is None


def test_to_dict_includes_hash_fields():
    """to_dict() exposes log_hash, previous_value, new_value."""
    with app.app_context():
        _trigger_log("dict_action", "dict_target", before="b", after="a")
        log = OperationLog.query.filter_by(action="dict_action").first()
        d = log.to_dict()
    assert "log_hash" in d
    assert "previous_value" in d
    assert "new_value" in d
    assert d["previous_value"] == "b"
    assert d["new_value"] == "a"


# ---------------------------------------------------------------------------
# Tests: verify endpoint — run non-destructive tests first
# ---------------------------------------------------------------------------


def test_verify_chain_ok():
    """GET /api/audit/logs/verify returns ok=True for an intact chain."""
    r = app.test_client().get(
        "/api/audit/logs/verify",
        headers=_auth(_admin_token),
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True
    assert data["violations"] == []
    assert data["total_checked"] >= 0


def test_verify_admin_only_viewer_forbidden():
    """Viewer cannot access the verify endpoint."""
    r = app.test_client().get(
        "/api/audit/logs/verify",
        headers=_auth(_viewer_token),
    )
    assert r.status_code == 403


def test_verify_skips_null_hash_logs():
    """Logs with log_hash=None (pre-migration) are skipped in verify without errors."""
    with app.app_context():
        legacy_log = OperationLog(
            action="legacy_action_null",
            target="legacy_target",
            details="old log without hash",
            created_by="system",
            log_hash=None,
        )
        db.session.add(legacy_log)
        db.session.commit()

    r = app.test_client().get(
        "/api/audit/logs/verify",
        headers=_auth(_admin_token),
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    # Should complete without error even with null-hash rows
    assert "ok" in data


# ---------------------------------------------------------------------------
# Destructive test: must run last as it corrupts a DB entry
# ---------------------------------------------------------------------------


def test_verify_chain_detects_corruption():
    """Corrupting a log_hash triggers a violation in verify."""
    tag = uuid.uuid4().hex[:6]
    action = f"corrupt_action_{tag}"

    _trigger_log(action, "corrupt_target")

    log_id = None
    with app.app_context():
        log = OperationLog.query.filter_by(action=action).first()
        assert log is not None
        log_id = log.id
        log.log_hash = "a" * 64  # corrupt the hash
        db.session.commit()

    r = app.test_client().get(
        "/api/audit/logs/verify",
        headers=_auth(_admin_token),
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is False
    assert len(data["violations"]) >= 1
    ids = [v["id"] for v in data["violations"]]
    assert log_id in ids
