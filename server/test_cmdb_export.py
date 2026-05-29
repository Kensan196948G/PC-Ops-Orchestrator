"""Tests for cmdb.export_cmdb_csv (Phase I-1, Issue #287)."""

import csv
import os
import sys

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from cmdb.export_cmdb_csv import export_cmdb_csv

SHEET = "管理番号ﾍﾞｰｽ"

# Header row with embedded newlines / half-width katakana, matching the
# physical ledger exactly.
HEADERS = [
    "導入年度",
    "管理番号",
    "社員番号",
    "貸与者名",
    "OS",
    "MACｱﾄﾞﾚｽ\n【有線】",
    "MACｱﾄﾞﾚｽ\n【無線】",
]

# (year, asset_number, employee_id, owner, os, mac_wired, mac_wireless)
SAMPLE_ROWS = [
    (2018, "PC-OLD", "E0001", "old user", "Windows 10", None, None),
    (2019, "PC-NEW1", "E1001", "山田太郎", "Windows 11", "00:11:22:33:44:55", None),
    (2025, "PC-NEW2", "E1002", "鈴木花子", "Windows 11", "AABBCCDDEEFF", None),
    (None, "PC-NOYEAR", "E1003", "佐藤次郎", "Windows 11", None, None),
    (None, None, None, None, None, None, None),  # blank 管理番号 -> skip
]


def _make_xlsx(path, sheet_name=SHEET, headers=HEADERS, rows=SAMPLE_ROWS):
    """Write a ledger-style xlsx to ``path``."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    wb.close()


def _read_csv(path):
    """Read a utf-8-sig CSV into (header, rows)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = list(csv.reader(fh))
    return reader[0], reader[1:]


def test_export_filters_and_year_handling(tmp_path):
    """min_year excludes old rows; no-year rows with asset number are kept."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    _make_xlsx(str(xlsx))

    result = export_cmdb_csv(str(xlsx), csv_path=str(out), min_year=2019)

    _header, rows = _read_csv(str(out))
    asset_numbers = [r[1] for r in rows]
    assert "PC-OLD" not in asset_numbers  # 2018 < 2019
    assert "PC-NEW1" in asset_numbers
    assert "PC-NEW2" in asset_numbers
    assert "PC-NOYEAR" in asset_numbers  # no year but has asset number
    assert result["rows"] == 3
    assert result["skipped"] >= 2  # blank-asset row + old row


def test_blank_asset_number_skipped(tmp_path):
    """Rows without 管理番号 are not emitted."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    _make_xlsx(str(xlsx))
    export_cmdb_csv(str(xlsx), csv_path=str(out), min_year=2019)
    _header, rows = _read_csv(str(out))
    assert all(r[1] for r in rows)


def test_header_with_newline_matched(tmp_path):
    """Newline-embedded MAC headers are matched and their values exported."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    _make_xlsx(str(xlsx))
    export_cmdb_csv(str(xlsx), csv_path=str(out), min_year=2019)
    header, rows = _read_csv(str(out))
    wired_idx = header.index("MACｱﾄﾞﾚｽ【有線】")
    by_asset = {r[1]: r for r in rows}
    assert by_asset["PC-NEW1"][wired_idx] == "00:11:22:33:44:55"


def test_csv_has_bom(tmp_path):
    """Output CSV is UTF-8 with BOM."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    _make_xlsx(str(xlsx))
    export_cmdb_csv(str(xlsx), csv_path=str(out), min_year=2019)
    with open(out, "rb") as fh:
        head = fh.read(3)
    assert head == b"\xef\xbb\xbf"


def test_existing_csv_backed_up(tmp_path):
    """An existing CSV is copied to the backup dir before overwrite."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    backup_dir = tmp_path / "Data-BackUp"
    _make_xlsx(str(xlsx))

    out.write_text("OLD CONTENT", encoding="utf-8-sig")
    result = export_cmdb_csv(
        str(xlsx), csv_path=str(out), min_year=2019, backup_dir=str(backup_dir)
    )

    assert result["backup"] is not None
    assert os.path.isfile(result["backup"])
    with open(result["backup"], encoding="utf-8-sig") as fh:
        assert "OLD CONTENT" in fh.read()
    # New file no longer holds old content.
    with open(out, encoding="utf-8-sig") as fh:
        assert "OLD CONTENT" not in fh.read()


def test_idempotent_two_runs(tmp_path):
    """Running twice yields identical data rows (second run backs up first)."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    backup_dir = tmp_path / "Data-BackUp"
    _make_xlsx(str(xlsx))

    export_cmdb_csv(
        str(xlsx), csv_path=str(out), min_year=2019, backup_dir=str(backup_dir)
    )
    _h1, rows1 = _read_csv(str(out))
    export_cmdb_csv(
        str(xlsx), csv_path=str(out), min_year=2019, backup_dir=str(backup_dir)
    )
    _h2, rows2 = _read_csv(str(out))
    assert rows1 == rows2


def test_missing_sheet_raises(tmp_path):
    """A missing sheet raises ValueError listing available sheets."""
    xlsx = tmp_path / "ledger.xlsx"
    out = tmp_path / "CMDB.csv"
    _make_xlsx(str(xlsx), sheet_name="WrongName")
    with pytest.raises(ValueError, match="not found"):
        export_cmdb_csv(str(xlsx), csv_path=str(out), sheet_name=SHEET)
