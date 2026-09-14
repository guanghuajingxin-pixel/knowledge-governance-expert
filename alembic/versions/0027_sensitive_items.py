"""add sensitive_items table

敏感信息管理：知识应用侧的敏感内容登记表（内容/类型/状态），
供问答与检索链路脱敏管控；content 全文唯一防重复登记。

Revision ID: 0027_sensitive_items
Revises: 0026_sync_tasks
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0027_sensitive_items'
down_revision: Union[str, None] = '0026_sync_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sensitive_items',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('content', sa.String(length=500), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False, server_default='custom'),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('content', name='uq_sensitive_items_content'),
    )


def downgrade() -> None:
    op.drop_table('sensitive_items')
