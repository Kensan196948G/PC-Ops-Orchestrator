"""add agent_signing_key column to pcs (Issue #188 part 4)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-15 22:30:00.000000

Issue #188 sub-task 4 — HMAC-SHA256 job signing.

Adds a per-PC signing key column to the pcs table. The server lazily issues a
fresh key (via secrets.token_urlsafe(64), ~88 chars base64url) the first time
an agent calls /api/collect with a NULL value, returns it once in the response,
and uses the same key for every subsequent HMAC-SHA256 signature over the
pending_tasks payload.

Per-PC keys (not a global secret) limit blast radius: a single compromised
host's key only lets an attacker forge tasks for that PC.

Column is nullable=True with no server_default — existing rows stay NULL until
the next collect call, at which point the server issues a key and rewrites the
row. New deployments start with NULL too. nullable=True avoids a SQLite
batch_op rewrite that would otherwise require backfilling every row.
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("agent_signing_key", sa.String(length=128), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("pcs", schema=None) as batch_op:
        batch_op.drop_column("agent_signing_key")
