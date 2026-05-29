"""Sidebar nav restructure tests (Phase I-UI, Issue #293 follow-up).

Phase I（PC情報取得 / CMDB台帳=正）方針に合わせ、不要なサイドメニュー4項目
（スケジュール / Agent管理 / ジョブテンプレート / 証明書管理）を base.html の
nav から除去した。route / template / JS は残置するため、直接 URL アクセスは
引き続き 200 を返す（後方互換）ことも検証する。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from auth import hash_password  # noqa: E402
from models import User  # noqa: E402

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            db.session.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin"),
                    role="admin",
                )
            )
            db.session.commit()


def _base_html():
    """Render any page extending base.html and return its HTML."""
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_removed_nav_links_absent_from_sidebar():
    html = _base_html()
    for href in (
        'href="/scheduled-tasks"',
        'href="/agents"',
        'href="/job-templates"',
        'href="/certs"',
    ):
        assert href not in html, f"removed nav link still present: {href}"


def test_kept_nav_links_present():
    html = _base_html()
    for href in ('href="/pcs"', 'href="/groups"', 'href="/alert-rules"'):
        assert href in html, f"expected nav link missing: {href}"


def test_no_dangling_agents_badge_reference():
    """Removing the Agent管理 nav also removed its badge; JS must not target it."""
    html = _base_html()
    assert "agents-badge" not in html
    assert "nav-certs" not in html


def test_removed_pages_routes_still_registered():
    """Routes/templates are kept (only nav links removed): URLs must not 404.

    Some page routes are auth-gated (e.g. /job-templates returns 401 without a
    token); the point is that the route still exists, so we assert it is not a
    404 (which would mean the route was removed).
    """
    for path in ("/scheduled-tasks", "/agents", "/job-templates", "/certs"):
        resp = client.get(path)
        assert resp.status_code != 404, f"route removed unexpectedly: {path}"
