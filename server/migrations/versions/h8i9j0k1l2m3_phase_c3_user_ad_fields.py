"""phase_c3_user_ad_fields

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-17 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ad_dn", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ad_synced_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_users_ad_dn"), ["ad_dn"], unique=False)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_ad_dn"))
        batch_op.drop_column("ad_synced_at")
        batch_op.drop_column("ad_dn")
