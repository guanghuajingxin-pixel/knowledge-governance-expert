"""Document-level retrieval switch for managed document libraries."""
from alembic import op
import sqlalchemy as sa

revision = "0036_document_retrieval_enabled"
down_revision = "0035_mineru_local_chunks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_documents",
                  sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade():
    op.drop_column("library_documents", "enabled")
