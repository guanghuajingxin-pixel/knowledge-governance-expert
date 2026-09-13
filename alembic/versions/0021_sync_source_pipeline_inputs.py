"""add pipeline_inputs to sync_sources

SyncSource 模型新增流水线分段参数字段：Dify 流水线数据集（runtime_mode=rag_pipeline）
的 pipeline/run 接口要求 inputs 携带流水线定义的必填变量（如 max_chunk_length、
parent_mode、child_length），缺失会报 500 "xxx is required in input form"。
不同流水线的 input form 变量完全不同，必须按同步源独立配置。
已有行回填空 JSON 对象，普通数据集忽略此字段。

Revision ID: 0021
Revises: 0020_add_kb_status
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0021_sync_source_pipeline_inputs'
down_revision: Union[str, None] = '0020_add_kb_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sync_sources',
                  sa.Column('pipeline_inputs', sa.Text(), nullable=False,
                            server_default='{}'))


def downgrade() -> None:
    op.drop_column('sync_sources', 'pipeline_inputs')
