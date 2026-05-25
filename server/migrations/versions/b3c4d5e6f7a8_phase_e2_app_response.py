"""Phase E-2 — AppResponseLog (Issue #247)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-25 19:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "app_response_logs" not in insp.get_table_names():
        op.create_table(
            "app_response_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pc_id", sa.Integer(), nullable=False),
            sa.Column("app_name", sa.String(128), nullable=False),
            sa.Column("response_time_ms", sa.Integer(), nullable=False),
            sa.Column("threshold_ms", sa.Integer(), nullable=True),
            sa.Column("is_slow", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["pc_id"], ["pcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_app_response_logs_pc_id", "app_response_logs", ["pc_id"])
        op.create_index(
            "ix_app_response_logs_app_name", "app_response_logs", ["app_name"]
        )
        op.create_index(
            "ix_app_response_logs_recorded_at", "app_response_logs", ["recorded_at"]
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "app_response_logs" in insp.get_table_names():
        op.drop_table("app_response_logs")
