"""Add project inspiration links.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('inspiration_link',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('project_id', 'url', name='uq_inspiration_project_url'),
        sqlite_autoincrement=True)
    op.create_index('ix_inspiration_link_project_id', 'inspiration_link', ['project_id'])


def downgrade():
    op.drop_index('ix_inspiration_link_project_id', table_name='inspiration_link')
    op.drop_table('inspiration_link')
