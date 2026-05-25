"""Tests for CollectionPolicy CRUD API (Issue #248)."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import PC, CollectionPolicy, PCGroup, User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_cp").first():
            admin = User(
                username="admin_cp",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


def teardown_module():
    with app.app_context():
        CollectionPolicy.query.delete()
        db.session.commit()


def _login():
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_cp", "password": "admin"}),
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _make_group(name="TestGroupCP"):
    with app.app_context():
        g = PCGroup.query.filter_by(name=name).first()
        if not g:
            g = PCGroup(
                name=name,
                description="test group for collection policies",
                created_by="admin_cp",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.session.add(g)
            db.session.commit()
        return g.id


def _make_pc(name="PC-CP-001"):
    with app.app_context():
        p = PC.query.filter_by(pc_name=name).first()
        if not p:
            p = PC(pc_name=name, status="online")
            db.session.add(p)
            db.session.commit()
        return p.id


def _cleanup_policies():
    with app.app_context():
        CollectionPolicy.query.delete()
        db.session.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Auth guard tests
# ──────────────────────────────────────────────────────────────────────────────


def test_list_requires_auth():
    r = _req("GET", "/api/collection-policies")
    assert r.status_code == 401


def test_create_requires_auth():
    r = _req("POST", "/api/collection-policies", data={"metric_type": "boot_time"})
    assert r.status_code == 401


def test_effective_requires_auth():
    r = _req("GET", "/api/collection-policies/effective/1")
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# List
# ──────────────────────────────────────────────────────────────────────────────


def test_list_empty():
    _cleanup_policies()
    tok = _login()
    r = _req("GET", "/api/collection-policies", token=tok)
    assert r.status_code == 200
    assert json.loads(r.data) == []


def test_list_returns_policies():
    _cleanup_policies()
    tok = _login()
    _req(
        "POST", "/api/collection-policies", token=tok, data={"metric_type": "boot_time"}
    )
    r = _req("GET", "/api/collection-policies", token=tok)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert len(body) == 1
    assert body[0]["metric_type"] == "boot_time"


# ──────────────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────────────


def test_create_global_policy():
    _cleanup_policies()
    tok = _login()
    r = _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "app_response", "frequency_minutes": 30},
    )
    assert r.status_code == 201
    body = json.loads(r.data)
    assert body["metric_type"] == "app_response"
    assert body["frequency_minutes"] == 30
    assert body["group_id"] is None
    assert body["is_enabled"] is True


def test_create_group_policy():
    _cleanup_policies()
    gid = _make_group()
    tok = _login()
    r = _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "network_ping", "group_id": gid, "frequency_minutes": 15},
    )
    assert r.status_code == 201
    body = json.loads(r.data)
    assert body["group_id"] == gid
    assert body["frequency_minutes"] == 15


def test_create_missing_metric_type():
    tok = _login()
    r = _req(
        "POST", "/api/collection-policies", token=tok, data={"frequency_minutes": 10}
    )
    assert r.status_code == 400


def test_create_invalid_metric_type():
    tok = _login()
    r = _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "invalid_xyz"},
    )
    assert r.status_code == 400


def test_create_invalid_frequency():
    tok = _login()
    r = _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "boot_time", "frequency_minutes": 0},
    )
    assert r.status_code == 400


def test_create_duplicate_policy():
    _cleanup_policies()
    tok = _login()
    _req(
        "POST", "/api/collection-policies", token=tok, data={"metric_type": "event_log"}
    )
    r = _req(
        "POST", "/api/collection-policies", token=tok, data={"metric_type": "event_log"}
    )
    assert r.status_code == 409


def test_create_nonexistent_group():
    tok = _login()
    r = _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "boot_time", "group_id": 999999},
    )
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Get single
# ──────────────────────────────────────────────────────────────────────────────


def test_get_policy():
    _cleanup_policies()
    tok = _login()
    created = json.loads(
        _req(
            "POST",
            "/api/collection-policies",
            token=tok,
            data={"metric_type": "boot_time"},
        ).data
    )
    r = _req("GET", f"/api/collection-policies/{created['id']}", token=tok)
    assert r.status_code == 200
    assert json.loads(r.data)["id"] == created["id"]


def test_get_nonexistent_policy():
    tok = _login()
    r = _req("GET", "/api/collection-policies/999999", token=tok)
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Update
# ──────────────────────────────────────────────────────────────────────────────


def test_update_frequency():
    _cleanup_policies()
    tok = _login()
    created = json.loads(
        _req(
            "POST",
            "/api/collection-policies",
            token=tok,
            data={"metric_type": "boot_time"},
        ).data
    )
    r = _req(
        "PUT",
        f"/api/collection-policies/{created['id']}",
        token=tok,
        data={"frequency_minutes": 120},
    )
    assert r.status_code == 200
    assert json.loads(r.data)["frequency_minutes"] == 120


def test_update_disable_policy():
    _cleanup_policies()
    tok = _login()
    created = json.loads(
        _req(
            "POST",
            "/api/collection-policies",
            token=tok,
            data={"metric_type": "boot_time"},
        ).data
    )
    r = _req(
        "PUT",
        f"/api/collection-policies/{created['id']}",
        token=tok,
        data={"is_enabled": False},
    )
    assert r.status_code == 200
    assert json.loads(r.data)["is_enabled"] is False


def test_update_invalid_metric_type():
    _cleanup_policies()
    tok = _login()
    created = json.loads(
        _req(
            "POST",
            "/api/collection-policies",
            token=tok,
            data={"metric_type": "boot_time"},
        ).data
    )
    r = _req(
        "PUT",
        f"/api/collection-policies/{created['id']}",
        token=tok,
        data={"metric_type": "not_valid"},
    )
    assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Delete
# ──────────────────────────────────────────────────────────────────────────────


def test_delete_policy():
    _cleanup_policies()
    tok = _login()
    created = json.loads(
        _req(
            "POST",
            "/api/collection-policies",
            token=tok,
            data={"metric_type": "network_ping"},
        ).data
    )
    r = _req("DELETE", f"/api/collection-policies/{created['id']}", token=tok)
    assert r.status_code == 200
    # Confirm gone
    r2 = _req("GET", f"/api/collection-policies/{created['id']}", token=tok)
    assert r2.status_code == 404


def test_delete_nonexistent():
    tok = _login()
    r = _req("DELETE", "/api/collection-policies/999999", token=tok)
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Effective policy
# ──────────────────────────────────────────────────────────────────────────────


def test_effective_policy_defaults():
    """PC with no group membership returns system defaults."""
    _cleanup_policies()
    pc_id = _make_pc()
    tok = _login()
    r = _req("GET", f"/api/collection-policies/effective/{pc_id}", token=tok)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["pc_id"] == pc_id
    assert "effective_policies" in body
    for metric in ("boot_time", "app_response", "network_ping", "event_log"):
        assert body["effective_policies"][metric]["metric_type"] == metric
        assert body["effective_policies"][metric]["is_enabled"] is True


def test_effective_policy_group_overrides_global():
    """Group-level policy takes precedence over global policy."""
    _cleanup_policies()
    gid = _make_group()
    pc_id = _make_pc()
    tok = _login()

    # Set global: boot_time = 60min
    _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "boot_time", "frequency_minutes": 60},
    )
    # Set group: boot_time = 10min
    _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "boot_time", "group_id": gid, "frequency_minutes": 10},
    )

    # Add PC to the group
    with app.app_context():
        pc = PC.query.get(pc_id)
        group = PCGroup.query.get(gid)
        pc.groups.append(group)
        db.session.commit()

    r = _req("GET", f"/api/collection-policies/effective/{pc_id}", token=tok)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["effective_policies"]["boot_time"]["frequency_minutes"] == 10
    assert body["effective_policies"]["boot_time"]["group_id"] == gid


def test_effective_policy_nonexistent_pc():
    tok = _login()
    r = _req("GET", "/api/collection-policies/effective/999999", token=tok)
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Filter query params
# ──────────────────────────────────────────────────────────────────────────────


def test_list_filter_by_metric_type():
    _cleanup_policies()
    tok = _login()
    _req(
        "POST", "/api/collection-policies", token=tok, data={"metric_type": "boot_time"}
    )
    _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "app_response"},
    )

    r = _req("GET", "/api/collection-policies?metric_type=boot_time", token=tok)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert all(p["metric_type"] == "boot_time" for p in body)


def test_list_filter_by_group_id():
    _cleanup_policies()
    gid = _make_group()
    tok = _login()
    _req(
        "POST", "/api/collection-policies", token=tok, data={"metric_type": "boot_time"}
    )
    _req(
        "POST",
        "/api/collection-policies",
        token=tok,
        data={"metric_type": "boot_time", "group_id": gid},
    )

    r = _req("GET", f"/api/collection-policies?group_id={gid}", token=tok)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert len(body) == 1
    assert body[0]["group_id"] == gid
