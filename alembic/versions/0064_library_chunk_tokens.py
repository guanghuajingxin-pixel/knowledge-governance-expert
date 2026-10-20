"""Persist per-chunk token stats for lexical recall.

弱 CPU 服务器上 15k 分段实时分词需 5 分钟+（BM25 召回必然超时）；
词频字典入库后查询期解析 + 打分为秒级。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0064_chunk_tokens"
down_revision = "0063_chunk_embeddings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_chunk_tokens",
        sa.Column("chunk_id", UUID(as_uuid=True),
                  sa.ForeignKey("library_chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tokens", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("library_chunk_tokens")
