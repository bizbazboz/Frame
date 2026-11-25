"""Store account-linked Reddit archive statistics and resumable sync progress."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reddit_sync',
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('social_account.id'), primary_key=True),
        sa.Column('username', sa.String(20), nullable=False),
        sa.Column('before', sa.BigInteger()),
        sa.Column('complete', sa.Boolean(), nullable=False),
        sa.Column('synced_at', sa.DateTime()))
    op.create_table('reddit_post',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('social_account.id'), nullable=False),
        sa.Column('reddit_id', sa.String(20), nullable=False),
        sa.Column('username', sa.String(20), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('subreddit', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('score', sa.Integer()),
        sa.Column('comments', sa.Integer()),
        sa.Column('nsfw', sa.Boolean(), nullable=False),
        sa.Column('retrieved_at', sa.DateTime()),
        sa.Column('synced_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('account_id', 'reddit_id', name='uq_reddit_post_account_id'))
    op.create_index('ix_reddit_post_account_id', 'reddit_post', ['account_id'])
    op.create_index('ix_reddit_post_created_at', 'reddit_post', ['created_at'])


def downgrade():
    op.drop_table('reddit_post')
    op.drop_table('reddit_sync')
