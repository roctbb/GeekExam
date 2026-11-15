"""Organize the shared teacher test catalog into named groups."""
from alembic import op
import sqlalchemy as sa

revision = 'e9b26a0d4c31'
down_revision = 'd8a15f9c3b20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('test_groups',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('name', sa.String(120), nullable=False),
                    sa.UniqueConstraint('name'))
    with op.batch_alter_table('tests') as batch:
        batch.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_tests_group_id', 'test_groups', ['group_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_tests_group_id', ['group_id'])


def downgrade():
    with op.batch_alter_table('tests') as batch:
        batch.drop_index('ix_tests_group_id')
        batch.drop_constraint('fk_tests_group_id', type_='foreignkey')
        batch.drop_column('group_id')
    op.drop_table('test_groups')
