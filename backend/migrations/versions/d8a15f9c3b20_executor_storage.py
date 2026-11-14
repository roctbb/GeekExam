"""Add immutable executor storage without changing existing answers or grades."""
from alembic import op
import sqlalchemy as sa

revision = 'd8a15f9c3b20'
down_revision = 'c7f04e8b2a19'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('answers', sa.Column('latest_execution_id', sa.String(36), nullable=True))
    op.create_table('execution_runs',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('submission_id', sa.String(36), nullable=False),
        sa.Column('answer_id', sa.Integer, sa.ForeignKey('answers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('snapshot', sa.JSON, nullable=False),
        sa.Column('result', sa.JSON), sa.Column('result_hash', sa.String(64)),
        sa.Column('state', sa.String(30), nullable=False), sa.Column('progress', sa.JSON),
        sa.Column('sequence', sa.Integer, nullable=False), sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('dispatched_at', sa.DateTime), sa.Column('lease_until', sa.DateTime), sa.Column('finished_at', sa.DateTime),
        sa.Column('applied', sa.Boolean, nullable=False))
    op.create_table('execution_uploads', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('answer_id', sa.Integer, sa.ForeignKey('answers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(240), nullable=False), sa.Column('artifact', sa.JSON, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False))
    op.create_table('execution_task_files', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('question_id', sa.Integer, sa.ForeignKey('questions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(240), nullable=False), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('is_public', sa.Boolean, nullable=False), sa.Column('read_only', sa.Boolean, nullable=False),
        sa.Column('include_in_check', sa.Boolean, nullable=False), sa.Column('artifact', sa.JSON, nullable=False),
        sa.Column('deleted_at', sa.DateTime))


def downgrade():
    op.drop_table('execution_task_files')
    op.drop_table('execution_uploads')
    op.drop_table('execution_runs')
    op.drop_column('answers', 'latest_execution_id')
