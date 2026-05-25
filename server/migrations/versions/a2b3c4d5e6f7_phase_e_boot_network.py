"""Phase E — BootTimeLog + NetworkPingLog (Issue #245, #246)

Revision ID: a2b3c4d5e6f7
Revises: 71e527563e4f
Create Date: 2026-05-25 19:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "71e527563e4f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "boot_time_logs" not in insp.get_table_names():
        op.create_table(
            "boot_time_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pc_id", sa.Integer(), nullable=False),
            sa.Column("boot_duration_seconds", sa.Integer(), nullable=False),
            sa.Column("boot_timestamp", sa.DateTime(), nullable=False),
            sa.Column("collected_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["pc_id"], ["pcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("boot_time_logs", schema=None) as batch_op:
            batch_op.create_index("ix_boot_time_logs_pc_id", ["pc_id"], unique=False)
            batch_op.create_index(
                "ix_boot_time_logs_collected_at", ["collected_at"], unique=False
            )

    if "network_ping_logs" not in insp.get_table_names():
        op.create_table(
            "network_ping_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pc_id", sa.Integer(), nullable=False),
            sa.Column("check_type", sa.String(length=32), nullable=False),
            sa.Column("target", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["pc_id"], ["pcs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("network_ping_logs", schema=None) as batch_op:
            batch_op.create_index(
                "ix_network_ping_logs_pc_id", ["pc_id"], unique=False
            )
            batch_op.create_index(
                "ix_network_ping_logs_check_type", ["check_type"], unique=False
            )
            batch_op.create_index(
                "ix_network_ping_logs_checked_at", ["checked_at"], unique=False
            )


def downgrade():
    op.drop_table("network_ping_logs")
    op.drop_table("boot_time_logs")
