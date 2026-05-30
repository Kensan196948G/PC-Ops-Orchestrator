"""Tests for GET /api/cmdb/list (Phase J-1, Issue #309)."""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from auth import hash_password  # noqa: E402
from models import PC, User  # noqa: E402

app = create_app("testing")
client = app.test_client()

_TOKEN = None


def setup_module():
    global _TOKEN
    with app.app_context():
        db.create_all()
        if not User.query.first():
            db.session.add(User(username="admin", password_hash=hash_password("admin"), role="admin"))
            db.session.commit()
        # Create test PC with CMDB fields
        if not PC.query.filter_by(pc_name="CMDB-TEST-01").first():
            pc = PC(
                pc_name="CMDB-TEST-01",
                asset_number="MGT-001",
                owner_name="テスト 太郎",
                employee_id="EMP001",
                deploy_year=2023,
                asset_source="ledger",
                ip_lan="192.168.1.1",
            )
            db.session.add(pc)
            db.session.commit()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    _TOKEN = r.get_json()["token"]


def _auth():
    return {"Authorization": f"Bearer {_TOKEN}"}


class TestCmdbList:
    def test_list_returns_200(self):
        r = client.get("/api/cmdb/list", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "pages" in body

    def test_list_contains_test_pc(self):
        r = client.get("/api/cmdb/list", headers=_auth())
        assert r.status_code == 200
        items = r.get_json()["items"]
        names = [i["pc_name"] for i in items]
        assert "CMDB-TEST-01" in names

    def test_list_search_by_asset_number(self):
        r = client.get("/api/cmdb/list?q=MGT-001", headers=_auth())
        assert r.status_code == 200
        items = r.get_json()["items"]
        assert len(items) >= 1
        assert any(i["asset_number"] == "MGT-001" for i in items)

    def test_list_search_by_owner(self):
        r = client.get("/api/cmdb/list?q=テスト", headers=_auth())
        assert r.status_code == 200
        items = r.get_json()["items"]
        assert len(items) >= 1

    def test_list_filter_by_source(self):
        r = client.get("/api/cmdb/list?asset_source=ledger", headers=_auth())
        assert r.status_code == 200
        items = r.get_json()["items"]
        for item in items:
            assert item["asset_source"] == "ledger"

    def test_list_pagination(self):
        r = client.get("/api/cmdb/list?page=1&per_page=10", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert body["per_page"] == 10
        assert body["page"] == 1

    def test_list_returns_cmdb_fields(self):
        r = client.get("/api/cmdb/list?q=MGT-001", headers=_auth())
        item = r.get_json()["items"][0]
        assert item["asset_number"] == "MGT-001"
        assert item["owner_name"] == "テスト 太郎"
        assert item["employee_id"] == "EMP001"
        assert item["deploy_year"] == 2023
        assert item["asset_source"] == "ledger"
        assert item["ip_lan"] == "192.168.1.1"

    def test_list_requires_auth(self):
        r = client.get("/api/cmdb/list")
        assert r.status_code == 401

    def test_cmdb_page_renders(self):
        r = client.get("/cmdb", headers=_auth())
        assert r.status_code == 200
        assert b"CMDB" in r.data
