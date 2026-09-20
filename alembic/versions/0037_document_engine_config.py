"""Per-document index settings override for managed document libraries."""
from alembic import op
import sqlalchemy as sa

revision = "0037_document_engine_config"
down_revision = "0036_document_retrieval_enabled"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_documents",
                  sa.Column("engine_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("library_documents", "engine_config")
