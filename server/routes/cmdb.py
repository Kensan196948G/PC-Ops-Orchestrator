"""CMDB ledger import / status API (Phase I-1, Issue #287)."""

import csv
import io
import os

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from auth import admin_required, login_required
from cmdb.import_cmdb import import_cmdb_rows
from extensions import db, limiter
from models import PC

cmdb_bp = Blueprint("cmdb", __name__, url_prefix="/api/cmdb")

# Root directory under which JSON-supplied import paths must reside.
# Repo layout: <repo>/CMDB and <repo>/server/routes/cmdb.py
_CMDB_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "CMDB")
)


def _resolve_cmdb_path(path):
    """Resolve ``path`` and ensure it stays inside the CMDB directory.

    Rejects absolute paths and ``..`` traversal by comparing the real path
    against ``_CMDB_ROOT``. Returns the safe absolute path, or ``None`` if the
    path escapes the allowed root.
    """
    if not path:
        return None
    # Treat the supplied path as relative to the CMDB root.
    candidate = os.path.realpath(os.path.join(_CMDB_ROOT, path))
    root_with_sep = _CMDB_ROOT + os.sep
    if candidate != _CMDB_ROOT and not candidate.startswith(root_with_sep):
        return None
    return candidate


@cmdb_bp.route("/import", methods=["POST"])
@admin_required
@limiter.limit("10 per minute")
def import_ledger():
    """Import CMDB rows from an uploaded CSV or a server-side CSV path."""
    dry_run = False
    min_year = 2019

    upload = request.files.get("file")
    if upload is not None:
        # multipart/form-data CSV upload
        form_dry = request.form.get("dry_run", "").lower()
        dry_run = form_dry in ("1", "true", "yes", "on")
        year_raw = request.form.get("min_year")
        if year_raw:
            try:
                min_year = int(year_raw)
            except ValueError:
                return jsonify({"error": "min_year must be an integer"}), 400
        wrapper = io.TextIOWrapper(upload.stream, encoding="utf-8-sig", newline="")
        try:
            rows = list(csv.DictReader(wrapper))
        except (csv.Error, UnicodeDecodeError) as exc:
            return jsonify({"error": f"could not parse CSV: {exc}"}), 400
    else:
        data = request.get_json(silent=True) or {}
        path = data.get("path")
        if not path:
            return jsonify({"error": "file upload or path required"}), 400
        dry_run = bool(data.get("dry_run", False))
        if "min_year" in data:
            try:
                min_year = int(data["min_year"])
            except (TypeError, ValueError):
                return jsonify({"error": "min_year must be an integer"}), 400
        safe_path = _resolve_cmdb_path(path)
        if safe_path is None:
            return jsonify({"error": "path must be inside the CMDB directory"}), 400
        if not os.path.isfile(safe_path):
            return jsonify({"error": "file not found"}), 400
        try:
            with open(safe_path, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            return jsonify({"error": f"could not read CSV: {exc}"}), 400

    result = import_cmdb_rows(rows, dry_run=dry_run, min_year=min_year)
    return jsonify(result), 200


@cmdb_bp.route("/status", methods=["GET"])
@login_required
def status():
    """Return CMDB ledger coverage summary."""
    ledger_pc_count = PC.query.filter(PC.asset_source.isnot(None)).count()
    last_synced = db.session.query(func.max(PC.ledger_synced_at)).scalar()
    sources = {"ledger": 0, "agent": 0, "winrm": 0}
    rows = (
        db.session.query(PC.asset_source, func.count(PC.id))
        .group_by(PC.asset_source)
        .all()
    )
    for source, count in rows:
        if source in sources:
            sources[source] = count
    return (
        jsonify(
            {
                "ledger_pc_count": ledger_pc_count,
                "last_synced_at": last_synced.isoformat() if last_synced else None,
                "sources": sources,
            }
        ),
        200,
    )
