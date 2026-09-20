"""LibraryDocument.tags."""
from alembic import op
import sqlalchemy as sa

revision = "0039_library_document_tags"
down_revision = "0038_library_document_timestamps"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_documents",
                  sa.Column("tags", sa.ARRAY(sa.String(64)), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")))


def downgrade():
    op.drop_column("library_documents", "tags")
