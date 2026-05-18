"""inquiry phase d4 (Issue #241)

Revision ID: 71e527563e4f
Revises: 3c39dbcb6860
Create Date: 2026-05-18 19:52:38.089636

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "71e527563e4f"
down_revision = "3c39dbcb6860"
branch_labels = None
depends_on = None


def upgrade():
    # Use if_not_exists guard via inspector to be idempotent against environments
    # where Flask-SQLAlchemy db.create_all() has already provisioned the table.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "inquiries" not in insp.get_table_names():
        op.create_table(
            "inquiries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pc_id", sa.Integer(), nullable=True),
            sa.Column("inquired_by", sa.String(length=255), nullable=False),
            sa.Column("subject", sa.String(length=512), nullable=False),
            sa.Column("symptom", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("known_issue_id", sa.Integer(), nullable=True),
            sa.Column("response", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["pc_id"], ["pcs.id"]),
            sa.ForeignKeyConstraint(["known_issue_id"], ["known_issues.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("inquiries", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_inquiries_pc_id"), ["pc_id"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_inquiries_status"), ["status"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_inquiries_known_issue_id"),
                ["known_issue_id"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_inquiries_created_at"),
                ["created_at"],
                unique=False,
            )


def downgrade():
    with op.batch_alter_table("inquiries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inquiries_created_at"))
        batch_op.drop_index(batch_op.f("ix_inquiries_known_issue_id"))
        batch_op.drop_index(batch_op.f("ix_inquiries_status"))
        batch_op.drop_index(batch_op.f("ix_inquiries_pc_id"))
    op.drop_table("inquiries")
