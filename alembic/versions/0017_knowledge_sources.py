"""add knowledge_sources

企业知识库注册表：统一登记钉钉知识库、Dify 数据集、业务系统等知识库。
系统内所有「选择知识库」的地方均从此表取数。

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017_knowledge_sources'
down_revision: Union[str, None] = '0016_dify_dingtalk_doc_mappings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'knowledge_sources',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_ks_type', 'knowledge_sources', ['source_type'])
    op.create_index('ix_ks_enabled', 'knowledge_sources', ['enabled'])


def downgrade() -> None:
    op.drop_index('ix_ks_enabled', table_name='knowledge_sources')
    op.drop_index('ix_ks_type', table_name='knowledge_sources')
    op.drop_table('knowledge_sources')
