"""Document libraries switch to MinerU: local chunk storage + parse job id."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0035_mineru_local_chunks"
down_revision = "0034_embedding_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("library_documents", sa.Column("engine_job_id", sa.String(128)))
    op.create_table("library_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("library_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True),
                  sa.ForeignKey("library_chunks.id", ondelete="CASCADE")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("important_keywords", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_library_chunks_document_id", "library_chunks", ["document_id"])


def downgrade():
    op.drop_table("library_chunks")
    op.drop_column("library_documents", "engine_job_id")
