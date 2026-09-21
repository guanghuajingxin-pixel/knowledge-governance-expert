"""同步身份按用户：sync_sources.owner_user_id + sync_runs.operator_source。

定时/后台同步没有登录上下文，用同步源 owner 的钉钉 unionId 调钉钉 API
（权限与 owner 实际可见范围一致）；owner 缺失或未绑定钉钉时回退全局
dingtalk_operator_union_id 服务账号，并在 sync_runs.operator_source 留痕。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0043_sync_source_owner"
down_revision = "0042_audit_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sync_sources", sa.Column(
        "owner_user_id", UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("sync_runs", sa.Column(
        "operator_source", sa.String(20), nullable=False, server_default=""))


def downgrade():
    op.drop_column("sync_runs", "operator_source")
    op.drop_column("sync_sources", "owner_user_id")
