"""Tests for Issue #250 — Microsoft Graph Windows Updates integration."""

import json
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, SystemSetting, User, WindowsUpdate

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_mg").first():
            admin = User(
                username="admin_mg",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


def _login():
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_mg", "password": "admin"}),
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _set_config(tenant_id="t1", client_id="c1", secret="s1"):
    with app.app_context():
        for key, val in [
            ("msgraph_tenant_id", tenant_id),
            ("msgraph_client_id", client_id),
            ("msgraph_client_secret", secret),
        ]:
            row = db.session.get(SystemSetting, key)
            if row:
                row.value = val
            else:
                db.session.add(SystemSetting(key=key, value=val))
        db.session.commit()


def _make_pc(name):
    with app.app_context():
        existing = PC.query.filter_by(pc_name=name).first()
        if existing:
            return existing.id
        pc = PC(pc_name=name, ip_address="10.3.1.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestMsGraphConfig:
    def test_get_config_requires_admin(self):
        r = _req("GET", "/api/msgraph/config")
        assert r.status_code == 401

    def test_get_config_returns_masked_secret(self):
        token = _login()
        _set_config()
        r = _req("GET", "/api/msgraph/config", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "config" in data
        assert data["config"]["msgraph_client_secret"] == "***"
        assert data["config"]["msgraph_tenant_id"] == "t1"

    def test_put_config_updates_values(self):
        token = _login()
        r = _req(
            "PUT",
            "/api/msgraph/config",
            token=token,
            data={"msgraph_tenant_id": "new-tenant"},
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["config"]["msgraph_tenant_id"] == "new-tenant"

    def test_put_config_rejects_unknown_keys(self):
        token = _login()
        r = _req("PUT", "/api/msgraph/config", token=token, data={"unknown_key": "val"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestMsGraphStatus:
    def test_status_requires_admin(self):
        r = _req("GET", "/api/msgraph/status")
        assert r.status_code == 401

    def test_status_not_configured(self):
        # Clear config
        with app.app_context():
            for key in (
                "msgraph_tenant_id",
                "msgraph_client_id",
                "msgraph_client_secret",
            ):
                row = db.session.get(SystemSetting, key)
                if row:
                    row.value = ""
            db.session.commit()

        token = _login()
        r = _req("GET", "/api/msgraph/status", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["connected"] is False

    def test_status_connected(self):
        _set_config()
        token = _login()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "value": [{"id": "org1", "displayName": "Test Org"}]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "tok123"}
        mock_token_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_token_resp):
            with patch("requests.get", return_value=mock_resp):
                r = _req("GET", "/api/msgraph/status", token=token)

        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["connected"] is True

    def test_status_connection_error(self):
        _set_config()
        token = _login()

        import requests as real_requests

        with patch(
            "requests.post", side_effect=real_requests.ConnectionError("refused")
        ):
            r = _req("GET", "/api/msgraph/status", token=token)

        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["connected"] is False
        assert "error" in data


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class TestMsGraphSync:
    def test_sync_requires_admin(self):
        r = _req("POST", "/api/msgraph/sync")
        assert r.status_code == 401

    def test_sync_fails_without_config(self):
        with app.app_context():
            for key in ("msgraph_tenant_id", "msgraph_client_id"):
                row = db.session.get(SystemSetting, key)
                if row:
                    row.value = ""
            db.session.commit()

        token = _login()
        r = _req("POST", "/api/msgraph/sync", token=token)
        assert r.status_code == 400

    def test_sync_creates_windows_update_records(self):
        _set_config()
        pc_id = _make_pc("GRAPH-PC-01")

        # Fetch the pc_name we just created
        with app.app_context():
            pc = PC.query.get(pc_id)
            pc_name = pc.pc_name

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "tok123"}
        mock_token_resp.raise_for_status = MagicMock()

        graph_id = "aaaa-1111"
        mock_graph_resp = MagicMock()
        mock_graph_resp.raise_for_status = MagicMock()
        mock_graph_resp.json.return_value = {
            "value": [
                {
                    "id": graph_id,
                    "deviceName": pc_name,
                    "osVersion": "10.0.22621",
                    "complianceState": "compliant",
                    "lastSyncDateTime": "2026-05-25T10:00:00Z",
                }
            ]
        }

        token = _login()
        with patch("requests.post", return_value=mock_token_resp):
            with patch("requests.get", return_value=mock_graph_resp):
                r = _req("POST", "/api/msgraph/sync", token=token)

        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["synced"] == 1
        assert data["total_devices"] == 1

        with app.app_context():
            wu = WindowsUpdate.query.filter_by(
                pc_id=pc_id, kb_id=f"GRAPH:{graph_id[:32]}"
            ).first()
            assert wu is not None
            assert wu.installed is True

    def test_sync_unmatched_device(self):
        _set_config()
        token = _login()

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "tok456"}
        mock_token_resp.raise_for_status = MagicMock()

        mock_graph_resp = MagicMock()
        mock_graph_resp.raise_for_status = MagicMock()
        mock_graph_resp.json.return_value = {
            "value": [
                {
                    "id": "bbbb-2222",
                    "deviceName": "NONEXISTENT-DEVICE",
                    "osVersion": "10.0.22621",
                    "complianceState": "noncompliant",
                    "lastSyncDateTime": None,
                }
            ]
        }

        with patch("requests.post", return_value=mock_token_resp):
            with patch("requests.get", return_value=mock_graph_resp):
                r = _req("POST", "/api/msgraph/sync", token=token)

        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["synced"] == 0
        assert "NONEXISTENT-DEVICE" in data["unmatched"]

    def test_sync_token_failure_returns_502(self):
        _set_config()
        token = _login()

        import requests as real_requests

        with patch("requests.post", side_effect=real_requests.HTTPError("401")):
            r = _req("POST", "/api/msgraph/sync", token=token)

        assert r.status_code == 502

    def test_sync_graph_failure_returns_502(self):
        _set_config()
        token = _login()

        import requests as real_requests

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {"access_token": "tok789"}
        mock_token_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_token_resp):
            with patch(
                "requests.get",
                side_effect=real_requests.HTTPError("403 Forbidden"),
            ):
                r = _req("POST", "/api/msgraph/sync", token=token)

        assert r.status_code == 502
