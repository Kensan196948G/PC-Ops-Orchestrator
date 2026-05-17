"""Phase B-2: Add approval workflow columns to job_executions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-17

Issue #214 — Phase B-2: requires_approval=true templates enter pending_approval status.
- Adds approved_by, approved_at, rejection_reason columns.
- Extends status CHECK constraint to include 'pending_approval'.
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "job_executions",
        recreate="always",
        table_kwargs={},
    ) as batch_op:
        batch_op.add_column(sa.Column("approved_by", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        batch_op.drop_constraint("ck_job_executions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_job_executions_status",
            "status IN ("
            "'pending','running','completed','failed','cancelled','pending_approval'"
            ")",
        )


def downgrade():
    with op.batch_alter_table(
        "job_executions",
        recreate="always",
        table_kwargs={},
    ) as batch_op:
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by")
        batch_op.drop_constraint("ck_job_executions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_job_executions_status",
            "status IN ('pending','running','completed','failed','cancelled')",
        )
