"""LibraryDocument: source + parsed_at + updated_at."""
from alembic import op
import sqlalchemy as sa

revision = "0038_library_document_timestamps"
down_revision = "0037_document_engine_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_documents",
                  sa.Column("source", sa.String(32), nullable=False, server_default="local"))
    op.add_column("library_documents",
                  sa.Column("parsed_at", sa.DateTime(), nullable=True))
    op.add_column("library_documents",
                  sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade():
    op.drop_column("library_documents", "updated_at")
    op.drop_column("library_documents", "parsed_at")
    op.drop_column("library_documents", "source")
