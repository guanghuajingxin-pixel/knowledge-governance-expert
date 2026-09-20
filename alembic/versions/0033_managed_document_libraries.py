"""Project-owned document libraries with replaceable processing engines."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0033_managed_document_libraries"
down_revision = "0032_ragflow_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_libraries", sa.Column("library_type", sa.String(20), nullable=False, server_default="external"))
    op.add_column("knowledge_libraries", sa.Column("engine_config", sa.JSON(), nullable=False, server_default='{}'))
    op.create_table("library_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("library_id", sa.Integer(), sa.ForeignKey("knowledge_libraries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("engine_document_id", sa.String(128)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_library_documents_library_id", "library_documents", ["library_id"])


def downgrade():
    op.drop_table("library_documents")
    op.drop_column("knowledge_libraries", "engine_config")
    op.drop_column("knowledge_libraries", "library_type")
