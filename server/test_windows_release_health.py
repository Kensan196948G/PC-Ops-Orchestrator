"""Tests for Windows Release Health RSS sync API (Issue #249 Phase E-4)."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import KnownIssue, User

app = create_app("testing")
client = app.test_client()

_RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Windows 11 Release History</title>
    <item>
      <title>KB5034121 — Windows 11 22H2 Update</title>
      <guid>https://support.microsoft.com/kb/5034121</guid>
      <link>https://support.microsoft.com/kb/5034121</link>
      <description>Known issue: Apps may crash after updating.</description>
      <pubDate>Tue, 09 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>KB5035853 — Windows 11 23H2 Update</title>
      <guid>https://support.microsoft.com/kb/5035853</guid>
      <link>https://support.microsoft.com/kb/5035853</link>
      <description>Known issue: BitLocker may prompt for recovery key.</description>
      <pubDate>Wed, 12 Mar 2024 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

_ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Windows Release Health</title>
  <entry>
    <id>https://example.com/atom/001</id>
    <title>Atom Issue One</title>
    <summary>Atom symptom description</summary>
    <link href="https://example.com/kb/atom-001"/>
    <updated>2024-01-10T00:00:00Z</updated>
  </entry>
</feed>"""


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_wrh").first():
            admin = User(
                username="admin_wrh",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


def teardown_module():
    with app.app_context():
        KnownIssue.query.filter_by(source="windows_release_health").delete()
        User.query.filter_by(username="admin_wrh").delete()
        db.session.commit()


def _login():
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin_wrh", "password": "admin"},
    )
    return resp.get_json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _mock_urlopen(xml_content: str):
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_content.encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _cleanup():
    with app.app_context():
        KnownIssue.query.filter_by(source="windows_release_health").delete()
        db.session.commit()


# ── Auth guard ───────────────────────────────────────────────────────────────


def test_sync_requires_auth():
    resp = client.post("/api/integration/windows-release-health/sync")
    assert resp.status_code == 401


def test_list_requires_auth():
    resp = client.get("/api/integration/windows-release-health/issues")
    assert resp.status_code == 401


# ── Sync endpoint ─────────────────────────────────────────────────────────────


def test_sync_rss_creates_issues():
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["synced"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["source"] == "windows_release_health"


def test_sync_rss_upserts_on_second_call():
    _cleanup()
    token = _login()
    mock_resp1 = _mock_urlopen(_RSS_SAMPLE)
    mock_resp2 = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp1):
        client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    with patch("urllib.request.urlopen", return_value=mock_resp2):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    data = resp.get_json()
    assert data["created"] == 0
    assert data["updated"] == 2


def test_sync_atom_feed():
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_ATOM_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
            json={"url": "https://example.com/atom"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["synced"] == 1
    assert data["created"] == 1


def test_sync_custom_url_in_response():
    _cleanup()
    token = _login()
    custom_url = "https://custom.example.com/feed"
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
            json={"url": custom_url},
        )
    assert resp.get_json()["feed_url"] == custom_url


def test_sync_network_error_returns_502():
    token = _login()
    import urllib.error

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    assert resp.status_code == 502
    assert "error" in resp.get_json()


def test_sync_invalid_xml_returns_422():
    token = _login()
    mock_resp = _mock_urlopen("<not valid xml>>>")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resp = client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    assert resp.status_code == 422


# ── List endpoint ─────────────────────────────────────────────────────────────


def test_list_empty_returns_ok():
    _cleanup()
    token = _login()
    resp = client.get(
        "/api/integration/windows-release-health/issues",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "windows_release_health"
    assert data["total"] == 0
    assert data["issues"] == []


def test_list_after_sync():
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )

    resp = client.get(
        "/api/integration/windows-release-health/issues",
        headers=_auth(token),
    )
    data = resp.get_json()
    assert data["total"] == 2
    titles = [i["title"] for i in data["issues"]]
    assert "KB5034121 — Windows 11 22H2 Update" in titles


def test_list_active_filter_default():
    """Default ?active=true only returns active issues."""
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )

    with app.app_context():
        issue = KnownIssue.query.filter_by(source="windows_release_health").first()
        issue.is_active = False
        db.session.commit()

    resp = client.get(
        "/api/integration/windows-release-health/issues",
        headers=_auth(token),
    )
    assert resp.get_json()["total"] == 1


def test_list_active_all_returns_all():
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )

    with app.app_context():
        issue = KnownIssue.query.filter_by(source="windows_release_health").first()
        issue.is_active = False
        db.session.commit()

    resp = client.get(
        "/api/integration/windows-release-health/issues?active=all",
        headers=_auth(token),
    )
    assert resp.get_json()["total"] == 2


def test_issue_dict_has_source_field():
    _cleanup()
    token = _login()
    mock_resp = _mock_urlopen(_RSS_SAMPLE)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        client.post(
            "/api/integration/windows-release-health/sync",
            headers=_auth(token),
        )
    resp = client.get(
        "/api/integration/windows-release-health/issues",
        headers=_auth(token),
    )
    issue = resp.get_json()["issues"][0]
    assert issue["source"] == "windows_release_health"
    assert "external_id" in issue
