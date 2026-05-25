"""Windows Release Health RSS sync blueprint (Issue #249 Phase E-4)."""

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import login_required
from extensions import db
from models import KnownIssue

bp = Blueprint(
    "windows_release_health",
    __name__,
    url_prefix="/api/integration/windows-release-health",
)

_SOURCE = "windows_release_health"
_DEFAULT_RSS_URL = "https://support.microsoft.com/api/rss/products/10/7/release-history"
_RSS_TIMEOUT = 10  # seconds


def _parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 / Atom XML and return normalized item dicts."""
    root = ET.fromstring(xml_text)

    # Detect Atom vs RSS
    atom_ns = "http://www.w3.org/2005/Atom"
    if root.tag == f"{{{atom_ns}}}feed":
        return _parse_atom(root, atom_ns)
    return _parse_rss(root)


def _parse_rss(root: ET.Element) -> list[dict]:
    items = []
    for item in root.iter("item"):
        guid_el = item.find("guid")
        title_el = item.find("title")
        desc_el = item.find("description")
        link_el = item.find("link")
        pub_el = item.find("pubDate")

        if title_el is None:
            continue

        items.append(
            {
                "external_id": (guid_el.text if guid_el is not None else None)
                or (link_el.text if link_el is not None else None),
                "title": (title_el.text or "").strip(),
                "symptoms": (desc_el.text or "").strip() if desc_el is not None else "",
                "resolution": (link_el.text or "").strip()
                if link_el is not None
                else "",
                "pub_date": (pub_el.text or "").strip() if pub_el is not None else None,
            }
        )
    return items


def _parse_atom(root: ET.Element, ns: str) -> list[dict]:
    items = []
    for entry in root.iter(f"{{{ns}}}entry"):
        id_el = entry.find(f"{{{ns}}}id")
        title_el = entry.find(f"{{{ns}}}title")
        summary_el = entry.find(f"{{{ns}}}summary")
        link_el = entry.find(f"{{{ns}}}link")
        updated_el = entry.find(f"{{{ns}}}updated")

        if title_el is None:
            continue

        href = link_el.get("href", "") if link_el is not None else ""
        items.append(
            {
                "external_id": (id_el.text or "").strip()
                if id_el is not None
                else href,
                "title": (title_el.text or "").strip(),
                "symptoms": (summary_el.text or "").strip()
                if summary_el is not None
                else "",
                "resolution": href,
                "pub_date": (updated_el.text or "").strip()
                if updated_el is not None
                else None,
            }
        )
    return items


def _upsert_item(item: dict) -> tuple[KnownIssue, bool]:
    """Insert or update KnownIssue. Returns (instance, created)."""
    ext_id = item["external_id"]
    existing = None
    if ext_id:
        existing = KnownIssue.query.filter_by(
            source=_SOURCE, external_id=ext_id
        ).first()

    if existing:
        existing.title = item["title"]
        existing.symptoms = item["symptoms"] or existing.symptoms
        existing.resolution = item["resolution"] or existing.resolution
        existing.updated_at = datetime.now(timezone.utc)
        return existing, False

    issue = KnownIssue(
        title=item["title"],
        symptoms=item["symptoms"],
        resolution=item["resolution"],
        source=_SOURCE,
        external_id=ext_id,
        severity="medium",
        is_active=True,
    )
    db.session.add(issue)
    return issue, True


@bp.route("/sync", methods=["POST"])
@login_required
def sync_windows_release_health():
    """POST /api/integration/windows-release-health/sync

    Fetches the Windows Release Health RSS feed and upserts into known_issues.
    Accepts optional JSON body: {"url": "<custom_feed_url>"}
    """
    data = request.get_json(silent=True) or {}
    feed_url = data.get("url") or _DEFAULT_RSS_URL

    try:
        req = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "PC-Ops-Orchestrator/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_RSS_TIMEOUT) as resp:
            xml_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return jsonify({"error": f"RSS fetch failed: {exc}"}), 502
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500

    try:
        items = _parse_feed(xml_text)
    except ET.ParseError as exc:
        return jsonify({"error": f"XML parse error: {exc}"}), 422

    created_count = 0
    updated_count = 0
    for item in items:
        _, is_new = _upsert_item(item)
        if is_new:
            created_count += 1
        else:
            updated_count += 1

    db.session.commit()

    return jsonify(
        {
            "synced": len(items),
            "created": created_count,
            "updated": updated_count,
            "source": _SOURCE,
            "feed_url": feed_url,
        }
    )


@bp.route("/issues", methods=["GET"])
@login_required
def list_wsr_issues():
    """GET /api/integration/windows-release-health/issues

    Returns known issues sourced from Windows Release Health RSS.
    Query params: ?active=true|false (default: true)
    """
    active_param = request.args.get("active", "true").lower()
    query = KnownIssue.query.filter_by(source=_SOURCE)
    if active_param != "all":
        is_active = active_param != "false"
        query = query.filter_by(is_active=is_active)

    issues = query.order_by(KnownIssue.created_at.desc()).all()
    return jsonify(
        {
            "source": _SOURCE,
            "total": len(issues),
            "issues": [i.to_dict() for i in issues],
        }
    )
