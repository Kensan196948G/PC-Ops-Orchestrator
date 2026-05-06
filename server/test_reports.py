"""Unit tests for /api/reports/* endpoints (Issue #76, M5-3)."""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            admin = User(
                username="admin",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


@pytest.fixture(scope="module")
def token():
    import json

    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/json"},
    )
    return json.loads(r.data)["token"]


def auth_get(path, token):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


# ── monthly JSON ──────────────────────────────────────────


def test_monthly_report_current_month(token):
    r = auth_get("/api/reports/monthly", token)
    assert r.status_code == 200
    data = r.get_json()
    assert "period" in data
    assert "pc" in data
    assert "tasks" in data
    assert "alerts" in data
    assert "sla" in data


def test_monthly_report_specific_month(token):
    r = auth_get("/api/reports/monthly?year=2026&month=4", token)
    assert r.status_code == 200
    data = r.get_json()
    assert data["period"] == "2026-04"


def test_monthly_report_invalid_month(token):
    r = auth_get("/api/reports/monthly?year=2026&month=13", token)
    assert r.status_code == 400


def test_monthly_report_invalid_year(token):
    r = auth_get("/api/reports/monthly?year=1999&month=1", token)
    assert r.status_code == 400


def test_monthly_report_structure(token):
    r = auth_get("/api/reports/monthly?year=2026&month=5", token)
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d["pc"]["total"], int)
    assert isinstance(d["pc"]["health_rate"], float)
    assert isinstance(d["tasks"]["success_rate"], float)
    assert isinstance(d["alerts"]["critical"], int)
    assert isinstance(d["sla"], float)


# ── monthly list ──────────────────────────────────────────


def test_monthly_list(token):
    r = auth_get("/api/reports/monthly/list", token)
    assert r.status_code == 200
    data = r.get_json()
    assert "reports" in data
    assert data["count"] == len(data["reports"])
    assert len(data["reports"]) == 12


def test_monthly_list_custom_count(token):
    r = auth_get("/api/reports/monthly/list?months=3", token)
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] == 3


# ── CSV export ───────────────────────────────────────────


def test_csv_export(token):
    r = auth_get("/api/reports/monthly/export.csv?year=2026&month=5", token)
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    body = r.data.decode("utf-8-sig")
    assert "項目" in body
    assert "2026-05" in body


def test_csv_export_has_sla_row(token):
    r = auth_get("/api/reports/monthly/export.csv?year=2026&month=5", token)
    body = r.data.decode("utf-8-sig")
    assert "SLA" in body


# ── PDF export ───────────────────────────────────────────


def test_pdf_export(token):
    r = auth_get("/api/reports/monthly/export.pdf?year=2026&month=5", token)
    assert r.status_code == 200
    assert r.content_type == "application/pdf"
    assert r.data[:4] == b"%PDF"


# ── auth guard ───────────────────────────────────────────


def test_monthly_report_requires_auth():
    r = client.get("/api/reports/monthly")
    assert r.status_code == 401


def test_csv_requires_auth():
    r = client.get("/api/reports/monthly/export.csv")
    assert r.status_code == 401


def test_pdf_requires_auth():
    r = client.get("/api/reports/monthly/export.pdf")
    assert r.status_code == 401
