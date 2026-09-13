"""add knowledge_libraries table

知识库抽象层：智能体检索用的统一「知识库」镜像注册表（仅 dify | ragflow）。
只登记 platform + dataset_id 引用，不支持导入解析；与 knowledge_sources（推送路径）相互独立。

Revision ID: 0025_knowledge_libraries
Revises: 0024_sync_source_backend_type
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0025_knowledge_libraries'
down_revision: Union[str, None] = '0024_sync_source_backend_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'knowledge_libraries',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=False),
        sa.Column('dataset_id', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('platform', 'dataset_id', name='uq_knowledge_library_platform_dataset'),
    )


def downgrade() -> None:
    op.drop_table('knowledge_libraries')
