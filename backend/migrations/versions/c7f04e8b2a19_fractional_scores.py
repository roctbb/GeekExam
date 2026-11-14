"""Preserve fractional answer scores and attempt totals.

Revision ID: c7f04e8b2a19
Revises: b908053c2b34
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7f04e8b2a19'
down_revision = 'b908053c2b34'
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (('answers', 'points'), ('attempts', 'total_points')):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.Integer(), type_=sa.Float(precision=53), existing_nullable=True)


def downgrade():
    bind = op.get_bind()
    # Refuse a lossy downgrade once half-point grades have been recorded.
    for table, column in (('answers', 'points'), ('attempts', 'total_points')):
        count = bind.execute(sa.text(
            f'SELECT count(*) FROM {table} WHERE {column} != CAST({column} AS INTEGER)'
        )).scalar_one()
        if count:
            raise RuntimeError('Нельзя округлять сохранённые дробные оценки при откате')
    for table, column in (('answers', 'points'), ('attempts', 'total_points')):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.Float(precision=53), type_=sa.Integer(), existing_nullable=True)
