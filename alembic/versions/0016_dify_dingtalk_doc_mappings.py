"""add dify_dingtalk_doc_mappings

钉钉文档同步到 Dify 后记录 Dify 文档 ↔ 钉钉节点映射，
检索召回时据此回填钉钉原始文档链接，引用来源可跳转钉钉知识库。

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016_dify_dingtalk_doc_mappings'
down_revision: Union[str, None] = '0015_directory_knowledge_owner'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dify_dingtalk_doc_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('dify_dataset_id', sa.String(length=64), nullable=False),
        sa.Column('dify_document_id', sa.String(length=64), nullable=False),
        sa.Column('dingtalk_node_id', sa.String(length=128), nullable=False),
        sa.Column('dingtalk_url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('name', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('method', sa.String(length=10), nullable=False, server_default='file'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_dddm_dataset', 'dify_dingtalk_doc_mappings', ['dify_dataset_id'])
    op.create_index('ix_dddm_dify_doc', 'dify_dingtalk_doc_mappings', ['dify_document_id'], unique=True)
    op.create_index('ix_dddm_dt_node', 'dify_dingtalk_doc_mappings', ['dingtalk_node_id'])


def downgrade() -> None:
    op.drop_index('ix_dddm_dt_node', table_name='dify_dingtalk_doc_mappings')
    op.drop_index('ix_dddm_dify_doc', table_name='dify_dingtalk_doc_mappings')
    op.drop_index('ix_dddm_dataset', table_name='dify_dingtalk_doc_mappings')
    op.drop_table('dify_dingtalk_doc_mappings')
