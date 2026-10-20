"""Persist per-chunk embeddings for document library retrieval.

检索时只 embed 查询语句，分段向量从本表读取（取代整库实时 embed）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0063_chunk_embeddings"
down_revision = "0062_portal_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_chunk_embeddings",
        sa.Column("chunk_id", UUID(as_uuid=True),
                  sa.ForeignKey("library_chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("library_chunk_embeddings")
