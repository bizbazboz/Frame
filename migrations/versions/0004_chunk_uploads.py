"""Add resumable upload sessions and indexed content hashes.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('photo_version', sa.Column('content_hash', sa.String(64), nullable=True))
    op.create_index('ix_photo_version_content_hash', 'photo_version', ['content_hash'])
    op.create_table('upload_session',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('owner', sa.String(255), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('label', sa.String(200), nullable=False),
        sa.Column('total_bytes', sa.BigInteger(), nullable=False),
        sa.Column('received_bytes', sa.BigInteger(), nullable=False),
        sa.Column('chunk_bytes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('version_id', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(500), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_upload_session_project_id', 'upload_session', ['project_id'])
    op.create_index('ix_upload_session_updated_at', 'upload_session', ['updated_at'])


def downgrade():
    op.drop_table('upload_session')
    with op.batch_alter_table('photo_version') as batch:
        batch.drop_index('ix_photo_version_content_hash')
        batch.drop_column('content_hash')
