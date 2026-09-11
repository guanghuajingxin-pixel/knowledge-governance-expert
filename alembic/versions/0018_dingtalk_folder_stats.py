"""add dingtalk_folder_stats

钉钉知识库文件夹统计快照：知识缺口页选中钉钉知识库后的数据源，
由刷新按钮触发后台全量遍历写入，查询接口只读快照。

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018_dingtalk_folder_stats'
down_revision: Union[str, None] = '0017_knowledge_sources'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dingtalk_folder_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('node_id', sa.String(length=128), nullable=False),
        sa.Column('path', sa.String(length=1000), nullable=False, server_default=''),
        sa.Column('document_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fetched_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('external_id', 'node_id', name='uq_dt_folder_node'),
    )
    op.create_index('ix_dtfs_external_id', 'dingtalk_folder_stats', ['external_id'])


def downgrade() -> None:
    op.drop_index('ix_dtfs_external_id', table_name='dingtalk_folder_stats')
    op.drop_table('dingtalk_folder_stats')
