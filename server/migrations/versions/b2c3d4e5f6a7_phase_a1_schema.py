"""phase a-1 schema: pc.os_build, network_interfaces, job_templates

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15 10:00:00.000000

Issue #174 — Phase A-1: DB schema extension for v1.1 roadmap.
- Adds os_build column to pcs (Windows build number capture).
- Creates network_interfaces table (multi-NIC support per PC).
- Creates job_templates table (PowerShell template skeleton for Phase B-1).
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("os_build", sa.String(length=64), nullable=True))

    op.create_table(
        "network_interfaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pc_id", sa.Integer(), nullable=False),
        sa.Column("interface_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("mac_address", sa.String(length=17), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("ipv6_address", sa.String(length=45), nullable=True),
        sa.Column("subnet_mask", sa.String(length=45), nullable=True),
        sa.Column("gateway", sa.String(length=45), nullable=True),
        sa.Column("dns_servers", sa.Text(), nullable=True),
        sa.Column("link_speed_mbps", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["pc_id"], ["pcs.id"]),
        sa.UniqueConstraint(
            "pc_id", "interface_name", name="uq_network_interface_pc_name"
        ),
    )
    with op.batch_alter_table("network_interfaces", schema=None) as batch_op:
        batch_op.create_index("ix_network_interfaces_pc_id", ["pc_id"], unique=False)

    op.create_table(
        "job_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category", sa.String(length=64), nullable=True, server_default="general"
        ),
        sa.Column("script_body", sa.Text(), nullable=True),
        sa.Column("parameters_schema", sa.Text(), nullable=True),
        sa.Column(
            "risk_level",
            sa.String(length=16),
            nullable=False,
            server_default="low",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low','medium','high')",
            name="ck_job_templates_risk_level",
        ),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_by", sa.String(length=255), nullable=True, server_default="system"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("name", name="uq_job_template_name"),
    )
    with op.batch_alter_table("job_templates", schema=None) as batch_op:
        batch_op.create_index("ix_job_templates_name", ["name"], unique=True)
        batch_op.create_index(
            "ix_job_templates_is_enabled", ["is_enabled"], unique=False
        )


def downgrade():
    with op.batch_alter_table("job_templates", schema=None) as batch_op:
        batch_op.drop_index("ix_job_templates_is_enabled")
        batch_op.drop_index("ix_job_templates_name")
    op.drop_table("job_templates")

    with op.batch_alter_table("network_interfaces", schema=None) as batch_op:
        batch_op.drop_index("ix_network_interfaces_pc_id")
    op.drop_table("network_interfaces")

    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.drop_column("os_build")
