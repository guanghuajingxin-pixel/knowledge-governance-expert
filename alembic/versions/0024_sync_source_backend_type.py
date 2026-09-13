"""add backend_type to sync_sources

同步目标引擎泛化：SyncSource 新增 backend_type（dify | ragflow），默认 dify，
历史行为完全不变。目标库标识仍复用 dify_dataset_id/dify_dataset_name 两列
（对 RAGFlow 存其 dataset_id/name），远端文档 ID 复用 sync_document_mappings.dify_document_id。

Revision ID: 0024
Revises: 0023_dingtalk_file_snapshots
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0024_sync_source_backend_type'
down_revision: Union[str, None] = '0023_dingtalk_file_snapshots'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sync_sources',
                  sa.Column('backend_type', sa.String(length=16), nullable=False,
                            server_default='dify'))


def downgrade() -> None:
    op.drop_column('sync_sources', 'backend_type')
