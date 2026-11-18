"""Track exam heartbeats and independently confirmed Guard evidence."""
from alembic import op
import sqlalchemy as sa

revision = 'f0c37b1e5a42'
down_revision = 'e9b26a0d4c31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('presence_configs',
        sa.Column('test_id',sa.Integer(),sa.ForeignKey('tests.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('guard_room_id',sa.String(36)),
        sa.Column('guard_room_name',sa.String(120)),
        sa.Column('configured_by',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('updated_at',sa.DateTime(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))
    op.create_table('presence_clients',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('attempt_id',sa.Integer(),sa.ForeignKey('attempts.id',ondelete='CASCADE'),nullable=False),
        sa.Column('token_digest',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('last_seen_at',sa.DateTime(),nullable=False),sa.Column('last_sequence',sa.Integer(),nullable=False),
        sa.Column('visible',sa.Boolean(),nullable=False))
    op.create_index('ix_presence_clients_attempt_id','presence_clients',['attempt_id'])
    op.create_table('presence_heartbeats',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('attempt_id',sa.Integer(),sa.ForeignKey('attempts.id',ondelete='CASCADE'),nullable=False),
        sa.Column('client_id',sa.String(36),sa.ForeignKey('presence_clients.id',ondelete='CASCADE'),nullable=False),
        sa.Column('sequence',sa.Integer(),nullable=False),sa.Column('received_at',sa.DateTime(),nullable=False),
        sa.Column('visible',sa.Boolean(),nullable=False),sa.UniqueConstraint('client_id','sequence',name='uq_presence_heartbeat_sequence'))
    op.create_index('ix_presence_heartbeat_attempt_time','presence_heartbeats',['attempt_id','received_at'])
    op.create_table('attempt_presence',
        sa.Column('attempt_id',sa.Integer(),sa.ForeignKey('attempts.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('guard_session_id',sa.String(36)),sa.Column('guard_device_id',sa.String(36)),
        sa.Column('guard_router_id',sa.String(36)),sa.Column('bound_client_id',sa.String(36)),
        sa.Column('binding_confirmed_at',sa.DateTime()),sa.Column('binding_observed_at',sa.DateTime()),sa.Column('bound_by',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('guard_state',sa.String(32),nullable=False),sa.Column('guard_reason',sa.String(80)),
        sa.Column('guard_since',sa.DateTime()),sa.Column('guard_last_confirmed_at',sa.DateTime()),
        sa.Column('guard_checked_at',sa.DateTime()),sa.Column('history_complete',sa.Boolean(),nullable=False))
    op.create_table('presence_events',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('test_id',sa.Integer(),sa.ForeignKey('tests.id',ondelete='CASCADE'),nullable=False),
        sa.Column('attempt_id',sa.Integer(),sa.ForeignKey('attempts.id',ondelete='CASCADE')),
        sa.Column('source_key',sa.String(64),nullable=False),sa.Column('kind',sa.String(40),nullable=False),
        sa.Column('router_id',sa.String(36)),sa.Column('started_at',sa.DateTime(),nullable=False),
        sa.Column('detected_at',sa.DateTime(),nullable=False),sa.Column('last_confirmed_at',sa.DateTime()),
        sa.Column('ended_at',sa.DateTime()),sa.Column('exam_continued_at',sa.DateTime()),
        sa.Column('review_required',sa.Boolean(),nullable=False),sa.Column('details',sa.JSON(),nullable=False),
        sa.Column('reviewed_at',sa.DateTime()),sa.Column('reviewed_by',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('review_note',sa.String(500)),sa.UniqueConstraint('test_id','source_key',name='uq_presence_event_source'))
    op.create_index('ix_presence_events_test_id','presence_events',['test_id'])
    op.create_index('ix_presence_events_attempt_id','presence_events',['attempt_id'])


def downgrade():
    for table in ['presence_events','attempt_presence','presence_heartbeats','presence_clients','presence_configs']:
        op.drop_table(table)
