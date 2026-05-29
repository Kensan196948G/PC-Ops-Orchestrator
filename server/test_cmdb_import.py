"""Tests for cmdb.import_cmdb and the /api/cmdb routes (Phase I-1, Issue #287)."""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from cmdb.import_cmdb import import_cmdb_rows, normalize_mac
from extensions import db
from models import PC, OperationLog, User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        users = {
            "admin": ("admin", "admin"),
            "viewer": ("viewer", "viewer"),
        }
        for username, (pw, role) in users.items():
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(
                        username=username,
                        password_hash=hash_password(pw),
                        role=role,
                    )
                )
        db.session.commit()


@pytest.fixture(scope="module")
def admin_token():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    return r.get_json()["token"]


@pytest.fixture(scope="module")
def viewer_token():
    r = client.post(
        "/api/auth/login", json={"username": "viewer", "password": "viewer"}
    )
    return r.get_json()["token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _row(**kw):
    """Build a CSV-style ledger row dict with sensible defaults."""
    base = {
        "導入年": "2020",
        "管理番号(コンピュータ名)": "PC-X",
        "貸与者名(CN)": "",
        "社員番号(SAM)": "",
        "OS": "Windows 11",
        "MACｱﾄﾞﾚｽ【有線】": "",
        "MACｱﾄﾞﾚｽ【無線】": "",
    }
    base.update(kw)
    return base


def _clear_pcs():
    """Remove all PC rows so each import test starts clean."""
    with app.app_context():
        PC.query.delete()
        db.session.commit()


# ---- normalize_mac unit tests ----


def test_normalize_mac_formats():
    """Colon, hyphen, and bare-hex MACs all normalize to colon upper-case."""
    assert normalize_mac("00:11:22:33:44:55")[0] == "00:11:22:33:44:55"
    assert normalize_mac("aa-bb-cc-dd-ee-ff")[0] == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("001122334455")[0] == "00:11:22:33:44:55"


def test_normalize_mac_invalid():
    """Invalid MAC returns (None, error)."""
    value, err = normalize_mac("not-a-mac")
    assert value is None
    assert err is not None


def test_normalize_mac_empty():
    """Empty / None MAC is absent, not an error."""
    assert normalize_mac("") == (None, None)
    assert normalize_mac(None) == (None, None)


# ---- import_cmdb_rows tests ----


def test_import_creates_pc_with_ledger_source():
    """A new PC is created with asset_source='ledger'."""
    _clear_pcs()
    with app.test_request_context():
        result = import_cmdb_rows(
            [_row(**{"管理番号(コンピュータ名)": "PC-NEW", "貸与者名(CN)": "山田"})]
        )
        assert result["created"] == 1
        pc = PC.query.filter_by(pc_name="PC-NEW").first()
        assert pc.asset_source == "ledger"
        assert pc.owner_name == "山田"
        assert pc.asset_number == "PC-NEW"
        assert pc.ledger_synced_at is not None


def test_import_updates_only_ledger_fields():
    """Existing agent-collected fields are preserved on update."""
    _clear_pcs()
    with app.test_request_context():
        pc = PC(
            pc_name="PC-UPD",
            os_version="agent-os",
            domain="agent-domain",
            asset_source="agent",
        )
        db.session.add(pc)
        db.session.commit()

        import_cmdb_rows(
            [
                _row(
                    **{
                        "管理番号(コンピュータ名)": "PC-UPD",
                        "貸与者名(CN)": "新担当",
                        "OS": "ledger-os",
                    }
                )
            ]
        )
        refreshed = PC.query.filter_by(pc_name="PC-UPD").first()
        assert refreshed.owner_name == "新担当"
        # agent-owned fields untouched
        assert refreshed.os_version == "agent-os"
        assert refreshed.domain == "agent-domain"


def test_import_preserves_agent_source():
    """asset_source stays 'agent' when already agent-owned."""
    _clear_pcs()
    with app.test_request_context():
        pc = PC(pc_name="PC-AG", asset_source="agent")
        db.session.add(pc)
        db.session.commit()
        import_cmdb_rows([_row(**{"管理番号(コンピュータ名)": "PC-AG"})])
        assert PC.query.filter_by(pc_name="PC-AG").first().asset_source == "agent"


def test_import_invalid_mac_nulls_field_but_keeps_row():
    """Invalid MAC -> field None + warning, row still imported."""
    _clear_pcs()
    with app.test_request_context():
        result = import_cmdb_rows(
            [
                _row(
                    **{
                        "管理番号(コンピュータ名)": "PC-BADMAC",
                        "MACｱﾄﾞﾚｽ【有線】": "ZZZZ",
                    }
                )
            ]
        )
        assert result["created"] == 1
        assert len(result["errors"]) == 1
        pc = PC.query.filter_by(pc_name="PC-BADMAC").first()
        assert pc.mac_wired is None


def test_import_blank_asset_skipped():
    """Rows with empty 管理番号 are skipped."""
    _clear_pcs()
    with app.test_request_context():
        result = import_cmdb_rows([_row(**{"管理番号(コンピュータ名)": ""})])
        assert result["created"] == 0
        assert result["skipped"] == 1


def test_import_year_filter():
    """Rows below min_year are skipped; no-year rows are kept."""
    _clear_pcs()
    with app.test_request_context():
        result = import_cmdb_rows(
            [
                _row(**{"管理番号(コンピュータ名)": "PC-OLD", "導入年": "2018"}),
                _row(**{"管理番号(コンピュータ名)": "PC-NOYR", "導入年": ""}),
            ],
            min_year=2019,
        )
        assert result["created"] == 1
        assert result["skipped"] == 1
        assert PC.query.filter_by(pc_name="PC-OLD").first() is None
        assert PC.query.filter_by(pc_name="PC-NOYR").first() is not None


def test_import_dry_run_does_not_commit():
    """dry_run rolls back; no rows persisted."""
    _clear_pcs()
    with app.test_request_context():
        result = import_cmdb_rows(
            [_row(**{"管理番号(コンピュータ名)": "PC-DRY"})], dry_run=True
        )
        assert result["created"] == 1
        assert PC.query.filter_by(pc_name="PC-DRY").first() is None


def test_import_logs_operation():
    """A real (committed) import writes an audit log entry."""
    _clear_pcs()
    with app.test_request_context():
        before = OperationLog.query.filter_by(action="cmdb_import").count()
        import_cmdb_rows([_row(**{"管理番号(コンピュータ名)": "PC-LOG"})])
        after = OperationLog.query.filter_by(action="cmdb_import").count()
        assert after == before + 1


# ---- API endpoint tests ----


def test_api_import_requires_auth():
    """Unauthenticated import is 401."""
    resp = client.post("/api/cmdb/import", json={"path": "CMDB.csv"})
    assert resp.status_code == 401


def test_api_import_requires_admin(viewer_token):
    """Non-admin import is 403."""
    resp = client.post(
        "/api/cmdb/import", json={"path": "CMDB.csv"}, headers=_headers(viewer_token)
    )
    assert resp.status_code == 403


def test_api_import_multipart(admin_token):
    """Admin can import via multipart CSV upload."""
    _clear_pcs()
    csv_bytes = (
        "導入年,管理番号(コンピュータ名),貸与者名(CN),社員番号(SAM),OS,"
        "MACｱﾄﾞﾚｽ【有線】,MACｱﾄﾞﾚｽ【無線】\r\n"
        "2021,PC-MP,担当,E5,Windows 11,00:11:22:33:44:55,\r\n"
    ).encode("utf-8-sig")
    data = {"file": (io.BytesIO(csv_bytes), "CMDB.csv")}
    resp = client.post(
        "/api/cmdb/import",
        data=data,
        content_type="multipart/form-data",
        headers=_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["created"] == 1


def test_api_import_path_traversal_rejected(admin_token):
    """Path traversal and absolute paths are rejected with 400."""
    resp1 = client.post(
        "/api/cmdb/import",
        json={"path": "../../etc/passwd"},
        headers=_headers(admin_token),
    )
    assert resp1.status_code == 400
    resp2 = client.post(
        "/api/cmdb/import",
        json={"path": "/etc/passwd"},
        headers=_headers(admin_token),
    )
    assert resp2.status_code == 400


def test_api_status_requires_auth():
    """Status endpoint requires login."""
    assert client.get("/api/cmdb/status").status_code == 401


def test_api_status_returns_summary(admin_token):
    """Status returns counts and source breakdown."""
    _clear_pcs()
    with app.test_request_context():
        import_cmdb_rows([_row(**{"管理番号(コンピュータ名)": "PC-ST"})])
    resp = client.get("/api/cmdb/status", headers=_headers(admin_token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert "ledger_pc_count" in body
    assert "sources" in body
    assert body["sources"]["ledger"] >= 1
