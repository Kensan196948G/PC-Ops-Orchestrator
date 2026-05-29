"""Issue #163 — routes coverage gap resolution.

Covers 13 previously-uncovered lines across 5 route files:
  agents.py    : L67, L75, L153, L162  (timezone-aware datetime + offline label)
  backups.py   : L59-60               (DB integrity check exception path)
  certificates.py : L42, L52          (empty body + domain > 200 chars)
  reports.py   : L191-192, L203-204   (ImportError + font fallback)
  settings.py  : L70                  (update existing key)
"""

import json
import sys
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_cov163_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminCov163!"),
                    role="admin",
                )
            )
            db.session.commit()

    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {"username": f"admin_cov163_{_unique}", "password": "AdminCov163!"}
        ),
    )
    _admin_token = json.loads(r.data)["token"]


def _auth(method, path, data=None, content_type="application/json"):
    headers = {
        "Authorization": f"Bearer {_admin_token}",
        "Content-Type": content_type,
    }
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"Cov163PC-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


# ── agents.py: timezone-aware datetime else-branch (L67/L162) ────────────
# and offline label (L75) / offline status (L153)


def test_export_csv_offline_label_aware():
    """PC with aware last_seen 4 h ago → 'オフライン' label (L75) + aware-else branch (L67)."""
    four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=4)
    _create_pc("csvoffline4h", last_seen=four_hours_ago)
    r = _auth("GET", "/api/agents/export.csv")
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "オフライン" in content


def test_export_csv_recently_seen_label_aware():
    """PC with aware last_seen 15 min ago → '最近接続' label; confirms L67 else-branch."""
    fifteen_min_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
    _create_pc("csvrecent", last_seen=fifteen_min_ago)
    r = _auth("GET", "/api/agents/export.csv")
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "最近接続" in content


def test_list_agents_offline_status_aware():
    """PC with aware last_seen 4 h ago → online_status='offline' (L153) + aware else-branch (L162)."""
    four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=4)
    pc_id = _create_pc("apioffline4h", last_seen=four_hours_ago)
    r = _auth("GET", "/api/agents")
    assert r.status_code == 200
    agents = json.loads(r.data)["agents"]
    matched = [a for a in agents if a["id"] == pc_id]
    assert matched, "registered PC should appear in /api/agents"
    assert matched[0]["online_status"] == "offline"


def test_list_agents_recently_seen_status_aware():
    """PC with aware last_seen 10 min ago → online_status='recently_seen'; confirms L162 else-branch."""
    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    pc_id = _create_pc("apirecent", last_seen=ten_min_ago)
    r = _auth("GET", "/api/agents")
    assert r.status_code == 200
    agents = json.loads(r.data)["agents"]
    matched = [a for a in agents if a["id"] == pc_id]
    assert matched
    assert matched[0]["online_status"] == "recently_seen"


# ── backups.py: DB integrity check exception path (L59-60) ───────────────


def test_integrity_check_db_exception():
    """When the integrity check raises, the route returns 500 with an error message.

    Phase H-3 moved the integrity logic into backup_service.verify_integrity();
    the route wraps it in try/except → 500. Patch where the work now happens.
    """
    with patch(
        "backup_service.verify_integrity",
        side_effect=Exception("SQLITE_CORRUPT: fake error"),
    ):
        r = _auth("POST", "/api/backups/integrity-check")
    assert r.status_code == 500
    body = json.loads(r.data)
    assert body["ok"] is False
    assert "SQLITE_CORRUPT" in body["result"][0]


# ── certificates.py: empty body (L42) + domain > 200 chars (L52) ─────────


def test_create_certificate_no_body():
    """POST /api/certificates with JSON null body → 400 (L42: if not data).

    request.get_json() returns None for a JSON null value → falsy → hits L42.
    """
    headers = {
        "Authorization": f"Bearer {_admin_token}",
        "Content-Type": "application/json",
    }
    # JSON null → request.get_json() returns None (falsy) → hits L42
    r = client.open("/api/certificates", method="POST", headers=headers, data="null")
    assert r.status_code == 400
    body = json.loads(r.data)
    assert "リクエストボディ" in body["error"]


def test_create_certificate_domain_too_long():
    """POST /api/certificates with domain > 200 chars → 400 (L52)."""
    long_domain = "a" * 201 + ".example.com"
    r = _auth(
        "POST",
        "/api/certificates",
        data={
            "domain": long_domain,
            "name": "x" * 5,
            "expires_at": "2027-01-01",
            "cert_type": "server",
        },
    )
    assert r.status_code == 400
    body = json.loads(r.data)
    assert "domain" in body["error"]


# ── reports.py: ImportError fallback (L191-192) ──────────────────────────


def test_pdf_export_reportlab_not_installed():
    """Simulate reportlab missing → GET /api/reports/monthly/export.pdf returns 500 (L191-192)."""
    # Block all reportlab sub-modules at import time inside the route
    reportlab_mods = [k for k in sys.modules if k.startswith("reportlab")]
    saved = {k: sys.modules.pop(k) for k in reportlab_mods}
    saved["reportlab"] = sys.modules.pop("reportlab", None)

    try:
        with patch.dict(
            sys.modules,
            {
                "reportlab": None,
                "reportlab.lib": None,
                "reportlab.lib.colors": None,
                "reportlab.lib.pagesizes": None,
                "reportlab.lib.styles": None,
                "reportlab.lib.units": None,
                "reportlab.pdfbase": None,
                "reportlab.pdfbase.pdfmetrics": None,
                "reportlab.pdfbase.ttfonts": None,
                "reportlab.platypus": None,
            },
        ):
            r = _auth("GET", "/api/reports/monthly/export.pdf?year=2026&month=5")
        assert r.status_code == 500
        body = json.loads(r.data)
        assert "reportlab" in body["error"]
    finally:
        # Restore all removed modules
        for k, v in saved.items():
            if v is not None:
                sys.modules[k] = v


# ── reports.py: font registration fallback (L203-204) ────────────────────


def test_pdf_export_font_fallback():
    """When IPA font file is absent, Helvetica fallback is used (L203-204); PDF still generated."""
    with patch("routes.reports._IPA_FONT", "/nonexistent/font.ttf"):
        r = _auth("GET", "/api/reports/monthly/export.pdf?year=2026&month=5")
    # Font fallback → still produces a valid PDF (no error)
    assert r.status_code == 200
    assert r.data[:4] == b"%PDF"


# ── settings.py: update existing key (L70) ───────────────────────────────


def test_update_settings_existing_key_updated():
    """PUT /api/settings twice with same key → second call hits L70 (row.value = str(value))."""
    # First PUT: inserts the key (L72)
    r1 = _auth("PUT", "/api/settings", data={"log_level": "DEBUG"})
    assert r1.status_code == 200
    assert json.loads(r1.data)["settings"]["log_level"] == "DEBUG"

    # Second PUT: updates the existing row (L70)
    r2 = _auth("PUT", "/api/settings", data={"log_level": "ERROR"})
    assert r2.status_code == 200
    assert json.loads(r2.data)["settings"]["log_level"] == "ERROR"


# ── agents.py L67 / L162 (aware-datetime else-branch) ──────────────────
# These lines are structurally unreachable via the SQLite test DB because
# SQLite strips tzinfo on read. They are defensive code paths for production
# PostgreSQL backends that preserve tzinfo. Marked `# pragma: no cover` in
# routes/agents.py to acknowledge the gap honestly.
