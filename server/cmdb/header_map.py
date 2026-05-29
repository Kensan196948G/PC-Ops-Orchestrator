"""Header normalization and column mapping for the CMDB asset ledger.

The physical Excel ledger headers contain embedded newlines and a mix of
full-width / half-width katakana. We NFKC-normalize and strip whitespace /
line breaks so header matching is robust against those variations rather than
relying on fixed column indexes.
"""

import unicodedata

__all__ = ["normalize", "LEDGER_HEADERS", "CSV_COLUMNS"]


def normalize(s):
    """Normalize a header / cell string for robust matching.

    Steps: NFKC normalization (folds full-width to half-width, etc.) ->
    remove line breaks and all whitespace -> strip. ``None`` becomes "".
    """
    if s is None:
        return ""
    text = unicodedata.normalize("NFKC", str(s))
    # Remove line breaks and every whitespace character (incl. ideographic
    # space U+3000, which NFKC already maps to a regular space).
    text = "".join(ch for ch in text if not ch.isspace())
    return text.strip()


# Normalized ledger header -> logical key.
# Keys here are already NFKC-normalized + whitespace-stripped, so they compare
# directly against ``normalize(cell_value)``.
LEDGER_HEADERS = {
    normalize("導入年度"): "deploy_year",
    normalize("管理番号"): "asset_number",
    normalize("社員番号"): "employee_id",
    normalize("貸与者名"): "owner_name",
    normalize("OS"): "os",
    normalize("MACｱﾄﾞﾚｽ\n【有線】"): "mac_wired",
    normalize("MACｱﾄﾞﾚｽ\n【無線】"): "mac_wireless",
}


# Output column order for CMDB.csv (human-facing report).
# Note: there is no IP column in the source ledger; the IP column is emitted
# but always left blank on import (back-filled in Phase I-2).
CSV_COLUMNS = [
    "導入年",
    "管理番号(コンピュータ名)",
    "IPアドレス(LAN/WiFi)",
    "貸与者名(CN)",
    "社員番号(SAM)",
    "OS",
    "MACｱﾄﾞﾚｽ【有線】",
    "MACｱﾄﾞﾚｽ【無線】",
]
