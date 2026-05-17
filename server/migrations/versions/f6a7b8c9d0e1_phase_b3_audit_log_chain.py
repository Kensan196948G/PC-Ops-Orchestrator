"""Phase B-3: Add immutable audit chain columns to operation_logs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("operation_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("log_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("previous_value", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("new_value", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("operation_logs", schema=None) as batch_op:
        batch_op.drop_column("new_value")
        batch_op.drop_column("previous_value")
        batch_op.drop_column("log_hash")
