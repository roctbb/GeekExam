"""Persist teacher notifications alongside confirmed Wi-Fi departures."""
from alembic import op
import sqlalchemy as sa

revision = 'b01c46a31f27'
down_revision = '70e31e9a522b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tests') as batch:
        batch.add_column(sa.Column('activated_by', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_tests_activated_by', 'users', ['activated_by'], ['id'], ondelete='SET NULL')
    op.create_table('exam_wifi_alerts',
        sa.Column('event_id', sa.String(36), sa.ForeignKey('presence_events.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), nullable=False))
    op.create_index('ix_exam_wifi_alert_due', 'exam_wifi_alerts', ['status', 'available_at'])
    op.execute('UPDATE presence_configs SET enabled = true WHERE require_guard AND NOT enabled')


def downgrade():
    op.drop_table('exam_wifi_alerts')
    with op.batch_alter_table('tests') as batch:
        batch.drop_constraint('fk_tests_activated_by', type_='foreignkey')
        batch.drop_column('activated_by')
