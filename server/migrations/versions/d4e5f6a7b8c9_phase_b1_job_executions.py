"""Phase B-1: Add job_executions table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("job_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pc_id",
            sa.Integer(),
            sa.ForeignKey("pcs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("parameters", sa.Text()),
        sa.Column("result_output", sa.Text()),
        sa.Column("result_exit_code", sa.Integer()),
        sa.Column(
            "requested_by", sa.String(255), nullable=False, server_default="system"
        ),
        sa.Column("executed_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp()
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="ck_job_executions_status",
        ),
    )
    op.create_index("ix_job_executions_template_id", "job_executions", ["template_id"])
    op.create_index("ix_job_executions_pc_id", "job_executions", ["pc_id"])
    op.create_index("ix_job_executions_status", "job_executions", ["status"])
    op.create_index("ix_job_executions_created_at", "job_executions", ["created_at"])


def downgrade():
    op.drop_index("ix_job_executions_created_at", table_name="job_executions")
    op.drop_index("ix_job_executions_status", table_name="job_executions")
    op.drop_index("ix_job_executions_pc_id", table_name="job_executions")
    op.drop_index("ix_job_executions_template_id", table_name="job_executions")
    op.drop_table("job_executions")
