"""入库审核：新增钉钉文件审核记录表 dingtalk_file_reviews。

按钉钉节点 ID 记录审核状态（通过/待确认/待更正）与审核人，
独立于 dingtalk_file_snapshots，快照刷新不影响已审核结果。
"""
from alembic import op
import sqlalchemy as sa

revision = "0044_dingtalk_file_reviews"
down_revision = "0043_sync_source_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dingtalk_file_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(20), nullable=False, server_default=""),
        sa.Column("reviewer", sa.String(100), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_dingtalk_file_reviews_node_id", "dingtalk_file_reviews",
                    ["node_id"], unique=True)


def downgrade():
    op.drop_index("ix_dingtalk_file_reviews_node_id", table_name="dingtalk_file_reviews")
    op.drop_table("dingtalk_file_reviews")
