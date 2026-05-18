"""stability insight: StabilityScore, DiskHealth, KnownIssue, PC.stability_score, EventLog.category, WindowsUpdate.reboot_at

Revision ID: 3c39dbcb6860
Revises: h8i9j0k1l2m3
Create Date: 2026-05-18 17:46:17.169437

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c39dbcb6860'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def _insp():
    from sqlalchemy import inspect as sa_inspect
    return sa_inspect(op.get_bind())


def _table_exists(table):
    return _insp().has_table(table)


def _col_exists(table, col):
    return any(c["name"] == col for c in _insp().get_columns(table))


def _idx_exists(table, idx):
    return any(i["name"] == idx for i in _insp().get_indexes(table))


def upgrade():
    # New tables may already exist if db.create_all() ran before this migration
    if not _table_exists('stability_scores'):
        op.create_table(
            'stability_scores',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('pc_id', sa.Integer(), nullable=False),
            sa.Column('score', sa.Float(), nullable=False),
            sa.Column('deductions', sa.Text(), nullable=True),
            sa.Column('analysis_days', sa.Integer(), nullable=True),
            sa.Column('calculated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['pc_id'], ['pcs.id'], name='fk_stability_scores_pc_id'),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _idx_exists('stability_scores', 'ix_stability_scores_pc_id'):
        op.create_index('ix_stability_scores_pc_id', 'stability_scores', ['pc_id'], unique=False)
    if not _idx_exists('stability_scores', 'ix_stability_scores_calculated_at'):
        op.create_index('ix_stability_scores_calculated_at', 'stability_scores', ['calculated_at'], unique=False)

    if not _table_exists('disk_health'):
        op.create_table(
            'disk_health',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('pc_id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.Integer(), nullable=False),
            sa.Column('source', sa.String(length=255), nullable=True),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('disk_label', sa.String(length=64), nullable=True),
            sa.Column('severity', sa.String(length=32), nullable=True),
            sa.Column('generated_at', sa.DateTime(), nullable=True),
            sa.Column('collected_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['pc_id'], ['pcs.id'], name='fk_disk_health_pc_id'),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _idx_exists('disk_health', 'ix_disk_health_pc_id'):
        op.create_index('ix_disk_health_pc_id', 'disk_health', ['pc_id'], unique=False)
    if not _idx_exists('disk_health', 'ix_disk_health_event_id'):
        op.create_index('ix_disk_health_event_id', 'disk_health', ['event_id'], unique=False)
    if not _idx_exists('disk_health', 'ix_disk_health_generated_at'):
        op.create_index('ix_disk_health_generated_at', 'disk_health', ['generated_at'], unique=False)

    if not _table_exists('known_issues'):
        op.create_table(
            'known_issues',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=512), nullable=False),
            sa.Column('kb_id', sa.String(length=32), nullable=True),
            sa.Column('event_ids', sa.Text(), nullable=True),
            sa.Column('symptoms', sa.Text(), nullable=True),
            sa.Column('resolution', sa.Text(), nullable=True),
            sa.Column('affected_os', sa.String(length=255), nullable=True),
            sa.Column('affected_models', sa.Text(), nullable=True),
            sa.Column('severity', sa.String(length=32), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _idx_exists('known_issues', 'ix_known_issues_kb_id'):
        op.create_index('ix_known_issues_kb_id', 'known_issues', ['kb_id'], unique=False)

    # alerts FK already applied in phase_c1 migration — skip to avoid name conflict
    # Add new columns only if they don't exist yet (db.create_all() may have pre-created them)
    if not _col_exists('event_logs', 'category'):
        with op.batch_alter_table('event_logs', schema=None) as batch_op:
            batch_op.add_column(sa.Column('category', sa.String(length=32), nullable=True))
    if not _idx_exists('event_logs', 'ix_event_logs_category'):
        op.create_index('ix_event_logs_category', 'event_logs', ['category'], unique=False)
    if not _idx_exists('event_logs', 'ix_event_logs_event_id'):
        op.create_index('ix_event_logs_event_id', 'event_logs', ['event_id'], unique=False)
    if not _idx_exists('event_logs', 'ix_event_logs_generated_at'):
        op.create_index('ix_event_logs_generated_at', 'event_logs', ['generated_at'], unique=False)

    pcs_cols = []
    if not _col_exists('pcs', 'stability_score'):
        pcs_cols.append(sa.Column('stability_score', sa.Float(), nullable=True))
    if not _col_exists('pcs', 'last_stability_calc_at'):
        pcs_cols.append(sa.Column('last_stability_calc_at', sa.DateTime(), nullable=True))
    if pcs_cols:
        with op.batch_alter_table('pcs', schema=None) as batch_op:
            for col in pcs_cols:
                batch_op.add_column(col)

    wu_cols = []
    if not _col_exists('windows_updates', 'reboot_at'):
        wu_cols.append(sa.Column('reboot_at', sa.DateTime(), nullable=True))
    if wu_cols:
        with op.batch_alter_table('windows_updates', schema=None) as batch_op:
            for col in wu_cols:
                batch_op.add_column(col)
    if not _idx_exists('windows_updates', 'ix_windows_updates_installed_at'):
        op.create_index('ix_windows_updates_installed_at', 'windows_updates', ['installed_at'], unique=False)
    if not _idx_exists('windows_updates', 'ix_windows_updates_kb_id'):
        op.create_index('ix_windows_updates_kb_id', 'windows_updates', ['kb_id'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('known_issues')
    op.drop_table('disk_health')
    op.drop_table('stability_scores')

    with op.batch_alter_table('windows_updates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_windows_updates_kb_id'))
        batch_op.drop_index(batch_op.f('ix_windows_updates_installed_at'))
        batch_op.drop_column('reboot_at')

    with op.batch_alter_table('pcs', schema=None) as batch_op:
        batch_op.drop_column('last_stability_calc_at')
        batch_op.drop_column('stability_score')

    with op.batch_alter_table('event_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_logs_generated_at'))
        batch_op.drop_index(batch_op.f('ix_event_logs_event_id'))
        batch_op.drop_index(batch_op.f('ix_event_logs_category'))
        batch_op.drop_column('category')

    # alerts FK skip (no downgrade needed)

    # ### end Alembic commands ###
