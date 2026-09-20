"""Knowledge library creator attribution."""
from alembic import op
import sqlalchemy as sa

revision = "0038_library_creator"
down_revision = "0037_document_engine_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_libraries", sa.Column("creator", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("knowledge_libraries", "creator")
