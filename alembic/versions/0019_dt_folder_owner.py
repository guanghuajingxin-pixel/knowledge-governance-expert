"""add owner to dingtalk_folder_stats

知识缺口页钉钉知识库文件夹支持维护知识Owner（单个编辑 + 批量导入），
刷新快照时按 node_id 保留已有 Owner。

Revision ID: 0019
Revises: 0018_dingtalk_folder_stats
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019_dt_folder_owner'
down_revision: Union[str, None] = '0018_dingtalk_folder_stats'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dingtalk_folder_stats',
                  sa.Column('owner', sa.String(length=200), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('dingtalk_folder_stats', 'owner')
