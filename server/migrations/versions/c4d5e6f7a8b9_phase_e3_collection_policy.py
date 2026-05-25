"""Phase E-3: CollectionPolicy table (Issue #248)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-25 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "collection_policies" not in insp.get_table_names():
        op.create_table(
            "collection_policies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=True),
            sa.Column("metric_type", sa.String(64), nullable=False),
            sa.Column(
                "frequency_minutes", sa.Integer(), nullable=False, server_default="60"
            ),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["pc_groups.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "group_id", "metric_type", name="uq_policy_group_metric"
            ),
        )
        op.create_index(
            "ix_collection_policies_group_id",
            "collection_policies",
            ["group_id"],
        )
        op.create_index(
            "ix_collection_policies_metric_type",
            "collection_policies",
            ["metric_type"],
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "collection_policies" in insp.get_table_names():
        op.drop_index(
            "ix_collection_policies_metric_type", table_name="collection_policies"
        )
        op.drop_index(
            "ix_collection_policies_group_id", table_name="collection_policies"
        )
        op.drop_table("collection_policies")
