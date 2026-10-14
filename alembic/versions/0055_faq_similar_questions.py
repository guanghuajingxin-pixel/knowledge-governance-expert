"""FAQ 相似问支持：faq_entries 新增 similar_questions / updated_at 列。

- similar_questions: ARRAY(String)，问题的问句变体；检索命中任一相似问即召回同一条答案，
  FAQ 列表中相似问不单列一条数据，始终归属其主问题
- updated_at: 与其余业务表对齐的行更新时间（server_default=now, onupdate=now）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0055_faq_similar_questions"
down_revision = "0054_remove_external_kb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "faq_entries",
        sa.Column("similar_questions", postgresql.ARRAY(sa.String()),
                  nullable=True, server_default="{}"),
    )
    op.add_column(
        "faq_entries",
        sa.Column("updated_at", sa.DateTime(), nullable=True,
                  server_default=sa.func.now()),
    )


def downgrade():
    with op.batch_alter_table("faq_entries") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("similar_questions")
