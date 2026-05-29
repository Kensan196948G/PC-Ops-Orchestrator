"""phase i-1 cmdb ledger: pc asset/ledger columns

Revision ID: c7a9e2b4d6f8
Revises: d5e6f7a8b9c0
Create Date: 2026-05-29 00:00:00.000000

Issue #287 — Phase I-1: CMDB asset ledger foundation.
Adds nullable asset/ledger columns to the pcs table so the Excel ledger can be
imported and reconciled with agent-collected data. All adds/indexes are guarded
by existence checks so the migration is idempotent on partially-migrated DBs.
"""

import sqlalchemy as sa
from alembic import op

revision = "c7a9e2b4d6f8"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


# (column_name, SQLAlchemy type, extra kwargs)
_LEDGER_COLUMNS = (
    ("asset_number", sa.String(length=64), {}),
    ("owner_name", sa.String(length=255), {}),
    ("employee_id", sa.String(length=64), {}),
    ("deploy_year", sa.Integer(), {}),
    ("ad_cn", sa.String(length=255), {}),
    ("ad_sam", sa.String(length=128), {}),
    ("ad_dn", sa.Text(), {}),
    ("ip_lan", sa.String(length=45), {}),
    ("ip_wifi", sa.String(length=45), {}),
    ("mac_wired", sa.String(length=17), {}),
    ("mac_wireless", sa.String(length=17), {}),
    ("asset_source", sa.String(length=16), {"server_default": "agent"}),
    ("ledger_synced_at", sa.DateTime(), {}),
)

# (index_name, column_name)
_LEDGER_INDEXES = (
    ("ix_pcs_asset_number", "asset_number"),
    ("ix_pcs_employee_id", "employee_id"),
    ("ix_pcs_ad_sam", "ad_sam"),
)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("pcs")}
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        for name, type_, kwargs in _LEDGER_COLUMNS:
            if name not in cols:
                batch_op.add_column(sa.Column(name, type_, nullable=True, **kwargs))

    existing_indexes = {ix["name"] for ix in insp.get_indexes("pcs")}
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        for index_name, column_name in _LEDGER_INDEXES:
            if index_name not in existing_indexes:
                batch_op.create_index(index_name, [column_name], unique=False)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in insp.get_indexes("pcs")}
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        for index_name, _column_name in reversed(_LEDGER_INDEXES):
            if index_name in existing_indexes:
                batch_op.drop_index(index_name)

    cols = {c["name"] for c in insp.get_columns("pcs")}
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        for name, _type, _kwargs in reversed(_LEDGER_COLUMNS):
            if name in cols:
                batch_op.drop_column(name)
