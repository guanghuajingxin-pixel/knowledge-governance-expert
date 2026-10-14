"""Dingtalk folder stats: mark .dlink shortcut rows (is_link)."""
from alembic import op
import sqlalchemy as sa

revision = "0058_dt_folder_is_link"
down_revision = "0057_knowledge_source_registry"
branch_labels = None
depends_on = None


def upgrade():
    # 存量快照行均为真实文件夹（旧遍历把 .dlink 计入父文档数，未单独成行），默认 false 即可
    op.add_column("dingtalk_folder_stats",
                  sa.Column("is_link", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade():
    op.drop_column("dingtalk_folder_stats", "is_link")
