"""Phase C-1: Add alert_rule_id FK to alerts table

Revision ID: g7h8i9j0k1l2
Revises: e5f6a7b8c9d0
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = "g7h8i9j0k1l2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("alert_rule_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index("ix_alerts_alert_rule_id", ["alert_rule_id"])
        batch_op.create_foreign_key(
            "fk_alerts_alert_rule_id",
            "alert_rules",
            ["alert_rule_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_constraint("fk_alerts_alert_rule_id", type_="foreignkey")
        batch_op.drop_index("ix_alerts_alert_rule_id")
        batch_op.drop_column("alert_rule_id")
