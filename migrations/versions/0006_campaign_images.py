"""Ordered images for campaigns, preserving each existing selected version."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('campaign_image',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaign.id'), nullable=False),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('photo_version.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.UniqueConstraint('campaign_id', 'version_id', name='uq_campaign_image_version'))
    op.create_index('ix_campaign_image_campaign_id', 'campaign_image', ['campaign_id'])
    op.create_index('ix_campaign_image_version_id', 'campaign_image', ['version_id'])
    op.execute('INSERT INTO campaign_image (campaign_id, version_id, position) SELECT id, version_id, 0 FROM campaign')


def downgrade():
    op.drop_table('campaign_image')
