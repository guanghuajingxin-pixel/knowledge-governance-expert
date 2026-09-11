"""知识加工：文档打标/摘要、知识关系、标签库。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSON

revision = "0014_add_knowledge_processing"
down_revision = "0013_collection_transfers"
branch_labels = None
depends_on = None


def upgrade():
    # 文档加工记录：存储 AI 打标/摘要结果
    op.create_table("processed_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", sa.String(64), nullable=False, index=True),
        sa.Column("document_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("tags", ARRAY(sa.String(64)), server_default="{}", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("keywords", ARRAY(sa.String(64)), server_default="{}", nullable=False),
        sa.Column("doc_type", sa.String(32), server_default="", nullable=False),
        sa.Column("process_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # 知识关系：文档间的语义关联
    op.create_table("knowledge_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_doc_id", sa.String(64), nullable=False, index=True),
        sa.Column("target_doc_id", sa.String(64), nullable=False, index=True),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), server_default="0", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_doc_id", "target_doc_id", "relation_type",
                            name="uq_knowledge_relation_triple"),
    )

    # 标签库：统一维护标签
    op.create_table("knowledge_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("color", sa.String(16), server_default="#409EFF", nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("knowledge_tags")
    op.drop_table("knowledge_relations")
    op.drop_table("processed_documents")
