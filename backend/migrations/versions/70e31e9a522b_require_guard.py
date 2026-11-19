"""Require Guard authorization only for tests that explicitly enable it."""
from alembic import op
import sqlalchemy as sa

revision = '70e31e9a522b'
down_revision = 'f0c37b1e5a42'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('presence_configs', sa.Column('require_guard', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('presence_configs', 'require_guard')
