"""Remember pre-rotation hashes for duplicate detection."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('photo_version_hash',
        sa.Column('digest', sa.String(64), primary_key=True),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('photo_version.id'), nullable=False))
    op.create_index('ix_photo_version_hash_version_id', 'photo_version_hash', ['version_id'])
    op.execute('INSERT INTO photo_version_hash (digest, version_id) SELECT content_hash, MIN(id) FROM photo_version WHERE content_hash IS NOT NULL GROUP BY content_hash')


def downgrade():
    op.drop_table('photo_version_hash')
