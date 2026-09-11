"""Directory knowledge owner imported from external tables."""
from alembic import op
import sqlalchemy as sa
revision = '0015_directory_knowledge_owner'
down_revision = '0014_add_knowledge_processing'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('directories', sa.Column('knowledge_owner', sa.String(200), nullable=False, server_default=''))


def downgrade():
    op.drop_column('directories', 'knowledge_owner')
