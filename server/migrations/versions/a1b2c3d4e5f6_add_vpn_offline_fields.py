"""add vpn offline sync fields to pcs

Revision ID: a1b2c3d4e5f6
Revises: 0c148e1838b7
Create Date: 2026-05-15 07:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "0c148e1838b7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "connection_type",
                sa.String(length=32),
                nullable=True,
                server_default="Unknown",
            )
        )
        batch_op.add_column(
            sa.Column(
                "offline_pending_count",
                sa.Integer(),
                nullable=True,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.drop_column("offline_pending_count")
        batch_op.drop_column("connection_type")
