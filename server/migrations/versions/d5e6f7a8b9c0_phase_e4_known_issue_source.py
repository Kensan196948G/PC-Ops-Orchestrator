"""Phase E-4: add source + external_id to known_issues

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("known_issues")}

    if "source" not in cols:
        op.add_column(
            "known_issues",
            sa.Column(
                "source", sa.String(64), nullable=False, server_default="internal"
            ),
        )
    if "external_id" not in cols:
        op.add_column(
            "known_issues",
            sa.Column("external_id", sa.String(512), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in insp.get_indexes("known_issues")}
    if "ix_known_issues_source" not in existing_indexes:
        op.create_index("ix_known_issues_source", "known_issues", ["source"])
    if "ix_known_issues_external_id" not in existing_indexes:
        op.create_index("ix_known_issues_external_id", "known_issues", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_known_issues_external_id", table_name="known_issues")
    op.drop_index("ix_known_issues_source", table_name="known_issues")
    op.drop_column("known_issues", "external_id")
    op.drop_column("known_issues", "source")
