"""Add local projects and preserve the existing library in Main library.

Revision ID: 0002
Revises: 0001
"""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    project = op.create_table('project',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False), sqlite_autoincrement=True)
    op.bulk_insert(project, [{'id': 1, 'name': 'Main library', 'created_at': datetime.utcnow()}])
    op.add_column('photo_group', sa.Column('project_id', sa.Integer(), nullable=True))
    op.execute(sa.text('UPDATE photo_group SET project_id = 1'))
    with op.batch_alter_table('photo_group') as batch:
        batch.alter_column('project_id', existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key('fk_photo_group_project_id_project', 'project', ['project_id'], ['id'])
        batch.create_index('ix_photo_group_project_id', ['project_id'])


def downgrade():
    # Photos remain intact; only project organisation is removed.
    with op.batch_alter_table('photo_group') as batch:
        batch.drop_index('ix_photo_group_project_id')
        batch.drop_constraint('fk_photo_group_project_id_project', type_='foreignkey')
        batch.drop_column('project_id')
    op.drop_table('project')
