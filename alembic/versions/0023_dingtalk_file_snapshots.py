"""add dingtalk_file_snapshots

钉钉知识库文件列表快照：知识加工 →「钉钉知识」页数据源。
全量遍历耗时 25–30 分钟且只在用户手动点「刷新」时执行，
因此遍历结果持久化在此表（进程重启/容器重建后列表仍可用），只保留最新一份。

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0023_dingtalk_file_snapshots'
down_revision: Union[str, None] = '0022_dingtalk_bindings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dingtalk_file_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('payload', sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('dingtalk_file_snapshots')
