"""用户密码策略：must_change_password + password_updated_at。

钉钉首次建档 / 管理员重置密码后 must_change_password=true，前端强制跳设密页；
password_updated_at 记录用户最近一次自主设密时间，null 表示从未设过可用密码。
历史用户回填 password_updated_at=created_at，保持老账号登录行为不变。
"""
from alembic import op
import sqlalchemy as sa

revision = "0041_user_password_flags"
down_revision = "0040_governance_standards"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column(
        "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("password_updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET password_updated_at = created_at WHERE password_updated_at IS NULL")


def downgrade():
    op.drop_column("users", "password_updated_at")
    op.drop_column("users", "must_change_password")
