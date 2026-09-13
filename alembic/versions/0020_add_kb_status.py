"""add status to knowledge_bases

KnowledgeBase 模型新增发布状态字段（PUBLISHING|FULLY_PUBLISHED|PARTIALLY_FAILED），
但历史迁移从未创建该列（本地开发库为手工同步 schema，严格走迁移的环境报
UndefinedColumnError: column knowledge_bases.status does not exist）。
已有行统一回填 FULLY_PUBLISHED。

Revision ID: 0020
Revises: 0019_dt_folder_owner
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0020_add_kb_status'
down_revision: Union[str, None] = '0019_dt_folder_owner'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('knowledge_bases',
                  sa.Column('status', sa.String(length=20), nullable=False,
                            server_default='FULLY_PUBLISHED'))


def downgrade() -> None:
    op.drop_column('knowledge_bases', 'status')
