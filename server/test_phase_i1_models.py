"""Tests for Phase I-1 PC ledger columns and migration (Issue #287)."""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC

app = create_app("testing")

LEDGER_KEYS = [
    "asset_number",
    "owner_name",
    "employee_id",
    "deploy_year",
    "ad_cn",
    "ad_sam",
    "ad_dn",
    "ip_lan",
    "ip_wifi",
    "mac_wired",
    "mac_wireless",
    "asset_source",
    "ledger_synced_at",
]


def setup_module():
    with app.app_context():
        db.create_all()


def test_pc_has_ledger_columns():
    """All ledger columns exist on the PC model."""
    columns = {c.name for c in PC.__table__.columns}
    for key in LEDGER_KEYS:
        assert key in columns, f"missing column {key}"


def test_to_dict_includes_ledger_keys():
    """PC.to_dict() exposes every ledger key."""
    with app.app_context():
        pc = PC(pc_name="DICT-PC")
        db.session.add(pc)
        db.session.commit()
        data = pc.to_dict()
        for key in LEDGER_KEYS:
            assert key in data, f"to_dict missing {key}"
        db.session.delete(pc)
        db.session.commit()


def test_pc_creatable_with_only_pc_name():
    """A PC can be saved with only pc_name (ledger columns nullable)."""
    with app.app_context():
        pc = PC(pc_name="MINIMAL-PC")
        db.session.add(pc)
        db.session.commit()
        fetched = PC.query.filter_by(pc_name="MINIMAL-PC").first()
        assert fetched is not None
        assert fetched.asset_number is None
        assert fetched.ledger_synced_at is None
        db.session.delete(fetched)
        db.session.commit()


def test_ledger_synced_at_isoformat():
    """ledger_synced_at serializes to ISO string when set, else None."""
    from datetime import datetime, timezone

    with app.app_context():
        pc = PC(pc_name="TS-PC", ledger_synced_at=datetime.now(timezone.utc))
        db.session.add(pc)
        db.session.commit()
        assert isinstance(pc.to_dict()["ledger_synced_at"], str)

        pc2 = PC(pc_name="TS-PC2")
        db.session.add(pc2)
        db.session.commit()
        assert pc2.to_dict()["ledger_synced_at"] is None
        db.session.delete(pc)
        db.session.delete(pc2)
        db.session.commit()


def test_migration_importable_and_down_revision():
    """The Phase I-1 migration imports and chains off the prior head."""
    mod = importlib.import_module(
        "migrations.versions.c7a9e2b4d6f8_phase_i1_cmdb_ledger"
    )
    assert mod.down_revision == "d5e6f7a8b9c0"
    assert mod.revision == "c7a9e2b4d6f8"
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
