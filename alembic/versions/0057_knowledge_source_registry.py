"""Knowledge source registry: code/priority/updated_by + built-in local_upload channel."""
from alembic import op
import sqlalchemy as sa

revision = "0057_knowledge_source_registry"
down_revision = "0056_business_credentials"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_sources", sa.Column("code", sa.String(64), nullable=True))
    op.add_column("knowledge_sources",
                  sa.Column("priority", sa.Integer(), server_default="99", nullable=False))
    op.add_column("knowledge_sources", sa.Column("updated_by", sa.String(100), nullable=True))

    # 回填编码：取 external_id（截断防超长），重复组追加 -{id} 去重后再建唯一索引
    op.execute("UPDATE knowledge_sources SET code = LEFT(external_id, 60)")
    op.execute("""
        UPDATE knowledge_sources ks SET code = ks.code || '-' || ks.id
        WHERE EXISTS (SELECT 1 FROM knowledge_sources k2
                      WHERE k2.code = ks.code AND k2.id <> ks.id)
    """)
    op.create_index("uq_knowledge_sources_code", "knowledge_sources", ["code"], unique=True)

    # 内置「本地上传」渠道（单条，幂等插入）
    op.execute("""
        INSERT INTO knowledge_sources (name, source_type, external_id, code, priority,
                                       description, enabled, created_at, updated_at)
        SELECT '本地上传', 'local_upload', 'local_upload', 'local_upload', 99,
               '平台内手动上传知识的内置来源渠道', true, NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM knowledge_sources WHERE source_type = 'local_upload')
    """)


def downgrade():
    op.execute("DELETE FROM knowledge_sources WHERE source_type = 'local_upload'")
    op.drop_index("uq_knowledge_sources_code", table_name="knowledge_sources")
    op.drop_column("knowledge_sources", "updated_by")
    op.drop_column("knowledge_sources", "priority")
    op.drop_column("knowledge_sources", "code")
