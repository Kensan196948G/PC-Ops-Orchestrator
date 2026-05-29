"""Import CMDB ledger rows into the ``pcs`` table.

Rows are dicts keyed by the CMDB CSV header names (see ``header_map.CSV_COLUMNS``).
Each row is upserted onto ``PC`` by ``pc_name`` (== 管理番号), touching only the
ledger-owned columns so agent/WinRM-collected fields are preserved.

Run as a module::

    python -m cmdb.import_cmdb --csv ../CMDB/CMDB.csv --dry-run
"""

import argparse
import csv
import re
from datetime import datetime, timezone

from extensions import db
from models import PC

try:  # package-relative import (normal case)
    from .header_map import normalize
except ImportError:  # pragma: no cover - fallback for direct script execution
    from header_map import normalize

__all__ = ["import_cmdb_rows", "normalize_mac"]

DEFAULT_MIN_YEAR = 2019

# CSV header names this importer reads (normalized for matching). Both the
# verbose export headers and the bare ledger headers are accepted.
_COL_ASSET = normalize("管理番号(コンピュータ名)")
_COL_ASSET_ALT = normalize("管理番号")
_COL_YEAR = normalize("導入年")
_COL_YEAR_ALT = normalize("導入年度")
_COL_OWNER = normalize("貸与者名(CN)")
_COL_OWNER_ALT = normalize("貸与者名")
_COL_EMP = normalize("社員番号(SAM)")
_COL_EMP_ALT = normalize("社員番号")
_COL_MAC_WIRED = normalize("MACｱﾄﾞﾚｽ【有線】")
_COL_MAC_WIRELESS = normalize("MACｱﾄﾞﾚｽ【無線】")

_MAC_DELIMITED_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
_MAC_BARE_RE = re.compile(r"^[0-9A-Fa-f]{12}$")

# Agent / WinRM ownership markers. Importing the ledger must never overwrite
# these so agent-managed rows stay distinguishable.
_AGENT_SOURCES = {"agent", "winrm"}

# Ledger-owned PC fields updated on import (used for diff tracking).
_LEDGER_FIELDS = (
    "asset_number",
    "owner_name",
    "employee_id",
    "deploy_year",
    "mac_wired",
    "mac_wireless",
)


def normalize_mac(value):
    """Normalize a MAC address to ``AA:BB:CC:DD:EE:FF`` form.

    Accepts colon- or hyphen-delimited or bare 12-hex strings. Returns
    ``(normalized, None)`` on success or ``(None, error_message)`` when the
    value is non-empty but not a valid MAC. Empty / ``None`` input returns
    ``(None, None)`` (absent, not an error).
    """
    if value is None:
        return None, None
    text = normalize(value)
    if not text:
        return None, None
    if _MAC_DELIMITED_RE.match(text):
        hex_only = text.replace(":", "").replace("-", "")
    elif _MAC_BARE_RE.match(text):
        hex_only = text
    else:
        return None, f"invalid MAC address: {value!r}"
    hex_only = hex_only.upper()
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)), None


def _get(row, *keys):
    """Return the first matching key's value from a row by normalized name."""
    norm_map = {normalize(k): v for k, v in row.items()}
    for key in keys:
        if key in norm_map:
            value = norm_map[key]
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    return None


def _parse_year(value):
    """Return the leading 4-digit year as int, or ``None``."""
    if value is None:
        return None
    text = normalize(value)
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
        else:
            break
    if len(digits) >= 4:
        try:
            return int(digits[:4])
        except ValueError:
            return None
    return None


def _apply_field(pc, changes, field, new_value):
    """Set ``field`` on ``pc``, recording old/new in ``changes`` if differing."""
    old_value = getattr(pc, field)
    if old_value != new_value:
        changes[field] = {"old": old_value, "new": new_value}
    setattr(pc, field, new_value)


def import_cmdb_rows(rows, *, dry_run=False, min_year=DEFAULT_MIN_YEAR):
    """Upsert ledger rows into the ``pcs`` table.

    Args:
        rows: Iterable of dicts keyed by CMDB CSV headers.
        dry_run: When True, the transaction is rolled back instead of committed.
        min_year: Rows whose deploy year is below this are skipped. Rows with no
            year but an asset number are still imported.

    Returns:
        dict with ``created``, ``updated``, ``skipped``, ``errors`` (list of
        warning strings), and ``diff`` (list of per-row change descriptors).
    """
    created = 0
    updated = 0
    skipped = 0
    errors = []
    diff = []
    now = datetime.now(timezone.utc)

    for line_no, row in enumerate(rows, start=1):
        asset_number = _get(row, _COL_ASSET, _COL_ASSET_ALT)
        if not asset_number:
            skipped += 1
            continue

        year = _parse_year(_get(row, _COL_YEAR, _COL_YEAR_ALT))
        if year is not None and year < min_year:
            skipped += 1
            continue

        owner_name = _get(row, _COL_OWNER, _COL_OWNER_ALT)
        employee_id = _get(row, _COL_EMP, _COL_EMP_ALT)

        mac_wired, err_wired = normalize_mac(_get(row, _COL_MAC_WIRED))
        if err_wired:
            errors.append(f"row {line_no} ({asset_number}) wired {err_wired}")
        mac_wireless, err_wireless = normalize_mac(_get(row, _COL_MAC_WIRELESS))
        if err_wireless:
            errors.append(f"row {line_no} ({asset_number}) wireless {err_wireless}")

        pc = PC.query.filter_by(pc_name=asset_number).first()
        if pc is None:
            pc = PC(pc_name=asset_number)
            db.session.add(pc)
            action = "created"
            created += 1
        else:
            action = "updated"
            updated += 1

        changes = {}
        new_values = {
            "asset_number": asset_number,
            "owner_name": owner_name,
            "employee_id": employee_id,
            "deploy_year": year,
            "mac_wired": mac_wired,
            "mac_wireless": mac_wireless,
        }
        for field in _LEDGER_FIELDS:
            _apply_field(pc, changes, field, new_values[field])

        # Preserve agent/WinRM ownership; otherwise mark as ledger-sourced.
        if pc.asset_source not in _AGENT_SOURCES:
            _apply_field(pc, changes, "asset_source", "ledger")

        pc.ledger_synced_at = now

        diff.append({"pc_name": asset_number, "action": action, "changes": changes})

    summary = (
        f"created={created} updated={updated} skipped={skipped} "
        f"errors={len(errors)} dry_run={dry_run}"
    )

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
        # Audit only real imports; log_operation commits its own row.
        # log_operation reads request-scoped fields (remote_addr / user_agent),
        # so it only runs inside a request context (the API route). CLI /
        # background imports commit without the request-scoped audit entry.
        from flask import has_request_context

        if has_request_context():
            from auth import log_operation

            log_operation(
                "cmdb_import",
                target=f"rows:{created + updated + skipped}",
                details=summary,
            )

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "diff": diff,
    }


def _main(argv=None):
    """CLI entry point: read a CSV and import it within an app context."""
    parser = argparse.ArgumentParser(description="Import CMDB CSV into the database")
    parser.add_argument("--csv", required=True, help="path to CMDB CSV (utf-8-sig)")
    parser.add_argument(
        "--dry-run", action="store_true", help="do not commit; report only"
    )
    parser.add_argument(
        "--min-year", type=int, default=DEFAULT_MIN_YEAR, help="minimum deploy year"
    )
    args = parser.parse_args(argv)

    from app import create_app

    app = create_app()
    with app.app_context():
        with open(args.csv, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        result = import_cmdb_rows(rows, dry_run=args.dry_run, min_year=args.min_year)
    print(
        f"created={result['created']} updated={result['updated']} "
        f"skipped={result['skipped']} errors={len(result['errors'])} "
        f"dry_run={args.dry_run}"
    )
    for err in result["errors"]:
        print(f"  WARN: {err}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
