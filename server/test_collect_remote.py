"""Tests for /api/collect/remote (Phase I-2, Issue #304).

Uses mock WinRM sessions so pywinrm does not need to be installed.
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from auth import hash_password  # noqa: E402
from models import User  # noqa: E402

app = create_app("testing")
client = app.test_client()

_ADMIN_TOKEN = None


def setup_module():
    global _ADMIN_TOKEN
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username="admin",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.data}"
    _ADMIN_TOKEN = r.get_json()["token"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth():
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _make_winrm_result(stdout: str, status_code: int = 0):
    r = MagicMock()
    r.status_code = status_code
    r.std_out = stdout.encode("utf-8")
    r.std_err = b""
    return r


def _mock_winrm_module(sysinfo_out: str, sw_out: str = "[]", upd_out: str = "[]"):
    mock_winrm = MagicMock()
    session_instance = MagicMock()
    session_instance.run_ps.side_effect = [
        _make_winrm_result(sysinfo_out),
        _make_winrm_result(sw_out),
        _make_winrm_result(upd_out),
    ]
    mock_winrm.Session.return_value = session_instance
    return mock_winrm


_SYSINFO_JSON = json.dumps(
    {
        "pc_name": "TESTPC01",
        "domain": "WORKGROUP",
        "os_version": "Windows 11 Pro",
        "os_build": "22631",
        "os_architecture": "64-bit",
        "cpu_name": "Intel Core i5-1240P",
        "cpu_cores": 12,
        "cpu_logical_processors": 16,
        "memory_total_gb": 16.0,
        "memory_available_gb": 8.5,
        "disk_total_gb": 476.0,
        "disk_free_gb": 200.0,
        "last_boot_time": "2026-05-30T01:00:00Z",
        "uptime_days": 0.5,
        "pending_reboot": False,
    }
)

_SW_JSON = json.dumps(
    [
        {
            "name": "Microsoft 365",
            "version": "16.0",
            "publisher": "Microsoft",
            "install_date": "2026-01-15",
        },
        {
            "name": "Google Chrome",
            "version": "124.0",
            "publisher": "Google LLC",
            "install_date": None,
        },
    ]
)

_UPD_JSON = json.dumps(
    [
        {
            "kb_id": "KB5037771",
            "title": "2024-05 累積更新",
            "installed": True,
            "installed_at": "2026-05-15T00:00:00Z",
        },
    ]
)


# ---------------------------------------------------------------------------
# winrm_collect unit tests (no Flask)
# ---------------------------------------------------------------------------


class TestWinrmCollectService:
    def test_is_winrm_configured_false_without_env(self, monkeypatch):
        import winrm_collect

        monkeypatch.delenv("WINRM_USER", raising=False)
        monkeypatch.delenv("WINRM_PASSWORD", raising=False)
        assert winrm_collect.is_winrm_configured() is False

    def test_is_winrm_configured_true_with_env(self, monkeypatch):
        import winrm_collect

        monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
        monkeypatch.setenv("WINRM_PASSWORD", "mirai")
        assert winrm_collect.is_winrm_configured() is True

    # TLS validation security tests
    def test_cert_validation_ssl_disabled(self):
        import winrm_collect

        assert (
            winrm_collect._cert_validation(use_ssl=False, allow_insecure=False)
            == "validate"
        )

    def test_cert_validation_ssl_enabled_defaults_to_validate(self):
        import winrm_collect

        assert (
            winrm_collect._cert_validation(use_ssl=True, allow_insecure=False)
            == "validate"
        )

    def test_cert_validation_ssl_insecure_requires_explicit_opt_in(self):
        import winrm_collect

        assert (
            winrm_collect._cert_validation(use_ssl=True, allow_insecure=True)
            == "ignore"
        )

    def test_insecure_off_by_default(self, monkeypatch):
        import winrm_collect

        monkeypatch.setenv("WINRM_USER", "u")
        monkeypatch.setenv("WINRM_PASSWORD", "p")
        monkeypatch.setenv("WINRM_SSL", "true")
        monkeypatch.delenv("WINRM_SSL_INSECURE", raising=False)
        _, _, _, _, use_ssl, allow_insecure, _ = winrm_collect._winrm_config()
        assert use_ssl is True
        assert allow_insecure is False
        assert winrm_collect._cert_validation(use_ssl, allow_insecure) == "validate"

    def test_collect_remote_raises_without_credentials(self, monkeypatch):
        import winrm_collect

        monkeypatch.delenv("WINRM_USER", raising=False)
        monkeypatch.delenv("WINRM_PASSWORD", raising=False)
        mock_winrm = MagicMock()
        with patch.dict(sys.modules, {"winrm": mock_winrm}):
            with pytest.raises(EnvironmentError, match="WINRM_USER"):
                winrm_collect.collect_remote("192.168.1.1")

    def test_collect_remote_returns_payload(self, monkeypatch):
        import winrm_collect

        monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
        monkeypatch.setenv("WINRM_PASSWORD", "mirai")
        mock_winrm = _mock_winrm_module(_SYSINFO_JSON, _SW_JSON, _UPD_JSON)
        with patch.dict(sys.modules, {"winrm": mock_winrm}):
            result = winrm_collect.collect_remote("192.168.1.50")
        assert result["pc_name"] == "TESTPC01"
        assert result["os_version"] == "Windows 11 Pro"
        assert len(result["software"]) == 2
        assert len(result["windows_updates"]) == 1
        assert result["collection_source"] == "winrm"

    def test_collect_remote_raises_on_ps_error(self, monkeypatch):
        import winrm_collect

        monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
        monkeypatch.setenv("WINRM_PASSWORD", "mirai")
        mock_winrm = MagicMock()
        session = MagicMock()
        err_result = MagicMock()
        err_result.status_code = 1
        err_result.std_out = b""
        err_result.std_err = b"Access denied"
        session.run_ps.return_value = err_result
        mock_winrm.Session.return_value = session
        with patch.dict(sys.modules, {"winrm": mock_winrm}):
            with pytest.raises(RuntimeError, match="PowerShell error"):
                winrm_collect.collect_remote("192.168.1.99")

    def test_collect_remote_software_failure_is_nonfatal(self, monkeypatch):
        import winrm_collect

        monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
        monkeypatch.setenv("WINRM_PASSWORD", "mirai")
        mock_winrm = MagicMock()
        session = MagicMock()
        err = MagicMock()
        err.status_code = 1
        err.std_out = b""
        err.std_err = b"err"
        session.run_ps.side_effect = [
            _make_winrm_result(_SYSINFO_JSON),
            err,
            _make_winrm_result(_UPD_JSON),
        ]
        mock_winrm.Session.return_value = session
        with patch.dict(sys.modules, {"winrm": mock_winrm}):
            result = winrm_collect.collect_remote("192.168.1.50")
        assert result["pc_name"] == "TESTPC01"
        assert result["software"] == []


# ---------------------------------------------------------------------------
# /api/collect/remote API tests (Flask)
# ---------------------------------------------------------------------------


def test_collect_remote_503_when_winrm_not_configured(monkeypatch):
    monkeypatch.delenv("WINRM_USER", raising=False)
    monkeypatch.delenv("WINRM_PASSWORD", raising=False)
    r = client.post(
        "/api/collect/remote",
        json={"target": "192.168.1.50"},
        headers=_auth(),
    )
    assert r.status_code == 503
    assert "WinRM" in r.get_json()["error"]


def test_collect_remote_400_without_target(monkeypatch):
    monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
    monkeypatch.setenv("WINRM_PASSWORD", "mirai")
    r = client.post(
        "/api/collect/remote",
        json={},
        headers=_auth(),
    )
    assert r.status_code == 400


def test_collect_remote_200_success(monkeypatch):
    monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
    monkeypatch.setenv("WINRM_PASSWORD", "mirai")
    mock_winrm = _mock_winrm_module(_SYSINFO_JSON, _SW_JSON, _UPD_JSON)
    with patch.dict(sys.modules, {"winrm": mock_winrm}):
        r = client.post(
            "/api/collect/remote",
            json={"target": "192.168.1.50"},
            headers=_auth(),
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["pc_name"] == "TESTPC01"
    assert body["software_count"] == 2
    assert body["update_count"] == 1
    assert body["collection_source"] == "winrm"


def test_collect_remote_200_with_pc_name_override(monkeypatch):
    monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
    monkeypatch.setenv("WINRM_PASSWORD", "mirai")
    mock_winrm = _mock_winrm_module(_SYSINFO_JSON, _SW_JSON, _UPD_JSON)
    with patch.dict(sys.modules, {"winrm": mock_winrm}):
        r = client.post(
            "/api/collect/remote",
            json={"target": "192.168.1.50", "pc_name": "MY-CUSTOM-PC"},
            headers=_auth(),
        )
    assert r.status_code == 200
    assert r.get_json()["pc_name"] == "MY-CUSTOM-PC"


def test_collect_remote_502_on_winrm_failure(monkeypatch):
    monkeypatch.setenv("WINRM_USER", ".\\mirai-user")
    monkeypatch.setenv("WINRM_PASSWORD", "mirai")
    mock_winrm = MagicMock()
    session = MagicMock()
    err = MagicMock()
    err.status_code = 1
    err.std_out = b""
    err.std_err = b"Connection refused"
    session.run_ps.return_value = err
    mock_winrm.Session.return_value = session
    with patch.dict(sys.modules, {"winrm": mock_winrm}):
        r = client.post(
            "/api/collect/remote",
            json={"target": "192.168.99.99"},
            headers=_auth(),
        )
    assert r.status_code == 502


def test_collect_remote_401_without_auth():
    r = client.post("/api/collect/remote", json={"target": "192.168.1.50"})
    assert r.status_code == 401
