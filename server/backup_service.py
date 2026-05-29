"""Shared backup/restore service layer (Phase H-3, Issue #285).

Single source of truth for the DB backup / restore / integrity subsystem.
Both ``routes/admin_ops.py`` and ``routes/backups.py`` delegate here so the
on-disk behaviour and the ``BackupJob`` ledger stay consistent.

Security note: ``restore_backup`` and the download endpoint operate on
caller-supplied filenames. ``_validate_backup_filename`` enforces a strict
allow-list (regex + path containment) to prevent path traversal.
"""

import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from extensions import db

# Default rotation depth: keep the newest N "pc_ops_*.db" backups.
_DEFAULT_MAX_KEEP = 10

# Allow-list for downloadable / restorable backup filenames.
# Only timestamped backups produced by perform_backup() are accepted.
# pre_restore_*.db snapshots deliberately use a different prefix so they are
# excluded from this allow-list and from rotation.
_BACKUP_FILENAME_RE = re.compile(r"^pc_ops_[0-9A-Za-z]+\.db$")

# Glob for rotation. pre_restore_*.db is a different prefix and is never
# matched here, so auto-saved pre-restore snapshots are never rotated away.
_BACKUP_GLOB = "pc_ops_*.db"


def _utc_ts() -> str:
    """Return a filesystem-safe UTC timestamp (e.g. 20260529T084530Z)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def db_path() -> Path:
    """Resolve the on-disk SQLite database path.

    Mirrors the historical ``admin_ops._db_path`` logic. For non-file
    URIs (``:memory:`` / empty) and non-sqlite dialects it falls back to
    ``<instance>/pc_ops.db`` so callers always get a concrete path.
    """
    db_url: str = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if db_url.startswith("sqlite:///"):
        rel = db_url[len("sqlite:///") :]
        if rel == ":memory:" or not rel:
            return Path(current_app.instance_path) / "pc_ops.db"
        p = Path(rel)
        if not p.is_absolute():
            p = Path(current_app.instance_path) / p
        return p
    return Path(current_app.instance_path) / "pc_ops.db"


def backup_dir() -> Path:
    """Return (creating if needed) the ``<instance>/backups`` directory."""
    bdir = Path(current_app.instance_path) / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


def is_sqlite() -> bool:
    """True when the active SQLAlchemy dialect is SQLite."""
    return db.engine.dialect.name == "sqlite"


def _is_memory_db() -> bool:
    """True for an in-memory SQLite DB.

    Disposing an in-memory engine destroys the shared database, so callers that
    swap the on-disk file (restore) must skip the dispose/reconnect dance —
    there is no file to reload and the live data lives in the connection pool.
    """
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    return ":memory:" in uri or uri in ("sqlite://", "sqlite:///")


def perform_backup(max_keep: int = _DEFAULT_MAX_KEEP) -> dict:
    """Create a real DB backup and rotate old ones.

    SQLite: uses ``sqlite3.Connection.backup`` (WAL-safe, online) to copy the
    live DB into ``<instance>/backups/pc_ops_<UTC ts>.db``, then keeps only the
    newest ``max_keep`` ``pc_ops_*.db`` files.

    Returns ``{"filename", "path", "size_bytes", "created_at"}``.

    Raises:
        NotImplementedError: when the dialect is not SQLite (pg_dump TBD).
        FileNotFoundError: when the source DB file does not exist.
    """
    if not is_sqlite():
        raise NotImplementedError(
            "pg_dump backup is not yet supported (Phase H-3 follow-up)"
        )

    src = db_path()
    if not src.exists():
        raise FileNotFoundError(f"source database not found: {src}")

    bdir = backup_dir()
    dest = bdir / f"pc_ops_{_utc_ts()}.db"

    # sqlite3.backup is safe under concurrent reads/writes (WAL-aware).
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    size_bytes = dest.stat().st_size

    # Rotate: keep only the newest max_keep "pc_ops_*.db" files.
    backups = sorted(bdir.glob(_BACKUP_GLOB), key=lambda f: f.stat().st_mtime)
    while len(backups) > max_keep:
        backups.pop(0).unlink(missing_ok=True)

    return {
        "filename": dest.name,
        "path": str(dest),
        "size_bytes": size_bytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def list_backup_files() -> list[dict]:
    """List available ``pc_ops_*.db`` backups (newest first)."""
    bdir = backup_dir()
    files = sorted(
        bdir.glob(_BACKUP_GLOB), key=lambda f: f.stat().st_mtime, reverse=True
    )
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        for f in files
    ]


def _validate_backup_filename(filename: str) -> str:
    """Validate a caller-supplied backup filename (path-traversal hardened).

    Defence layer 1: the filename must be a bare basename matching
    ``^pc_ops_[0-9A-Za-z]+\\.db$``. This rejects empty strings, anything
    containing ``/``, ``\\``, ``..`` or path separators, absolute paths, and
    the ``pre_restore_*`` snapshots.

    Defence layer 2: after joining to ``backup_dir()`` the resolved path must
    still live directly under the resolved backup directory. This catches any
    edge case the regex might miss (symlinks, normalisation surprises).

    Returns the validated basename. Raises ``ValueError`` on any violation.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("filename is required")

    # Reject anything that is not a bare, well-formed basename. The regex
    # forbids "/", "\\", "..", leading dots, and absolute paths implicitly.
    if not _BACKUP_FILENAME_RE.fullmatch(filename):
        raise ValueError(f"invalid backup filename: {filename!r}")

    bdir = backup_dir().resolve()
    candidate = (bdir / filename).resolve()

    # Second defence: ensure the resolved path is contained in backup_dir and
    # is a direct child (no nesting via traversal).
    if candidate.parent != bdir:
        raise ValueError(f"invalid backup path: {filename!r}")

    return filename


def restore_backup(filename: str) -> dict:
    """Restore the live SQLite DB from a previously created backup.

    Steps:
      1. validate ``filename`` (path-traversal hardened),
      2. ensure the target backup exists,
      3. snapshot the current DB to ``pre_restore_<UTC ts>.db`` (separate
         prefix; excluded from rotation and the download allow-list),
      4. copy the chosen backup over the live DB path,
      5. verify integrity; on failure auto-rollback from the snapshot and
         raise ``RuntimeError``.

    Returns ``{"restored_from", "pre_restore_backup", "integrity_ok"}``.

    Raises:
        NotImplementedError: non-SQLite dialect.
        ValueError: invalid filename.
        FileNotFoundError: target backup does not exist.
        RuntimeError: post-restore integrity check failed (after rollback).
    """
    if not is_sqlite():
        raise NotImplementedError(
            "pg_dump restore is not yet supported (Phase H-3 follow-up)"
        )

    safe_name = _validate_backup_filename(filename)
    bdir = backup_dir()
    source = bdir / safe_name
    if not source.exists():
        raise FileNotFoundError(f"backup not found: {safe_name}")

    target = db_path()

    # Auto-save the current DB before overwriting it. Distinct prefix keeps it
    # out of rotation and out of the download/restore allow-list.
    pre_restore = bdir / f"pre_restore_{_utc_ts()}.db"
    if target.exists():
        shutil.copy2(target, pre_restore)

    # Swap in the chosen backup.
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    # Dispose pooled connections so the next check opens the freshly restored
    # file rather than a stale handle to the previous DB. An in-memory DB has
    # no backing file; disposing it would destroy the live data, so skip it.
    memory_db = _is_memory_db()
    if not memory_db:
        db.session.remove()
        db.engine.dispose()

    integrity = verify_integrity()
    if not integrity.get("ok"):
        # Roll back: restore the pre-restore snapshot over the live DB.
        if pre_restore.exists():
            shutil.copy2(pre_restore, target)
            if not memory_db:
                db.session.remove()
                db.engine.dispose()
        raise RuntimeError(
            "restored database failed integrity check; rolled back "
            f"(result={integrity.get('result')})"
        )

    return {
        "restored_from": safe_name,
        "pre_restore_backup": pre_restore.name if pre_restore.exists() else None,
        "integrity_ok": True,
    }


def verify_integrity() -> dict:
    """Verify database integrity, dispatching on dialect.

    SQLite: runs ``PRAGMA integrity_check`` and returns its rows.
    Other dialects: ``PRAGMA`` is sqlite-only, so we fall back to a ``SELECT 1``
    connectivity probe and report ``ok`` when it succeeds.

    Returns ``{"ok": bool, "result": list[str]}``.
    """
    if is_sqlite():
        rows = db.session.execute(db.text("PRAGMA integrity_check")).fetchall()
        result = [r[0] for r in rows]
        ok = bool(result) and result[0] == "ok"
        return {"ok": ok, "result": result}

    # Non-SQLite: integrity_check is unavailable; verify connectivity instead.
    db.session.execute(db.text("SELECT 1")).fetchall()
    return {
        "ok": True,
        "result": ["connection ok (integrity_check is sqlite-only)"],
    }
