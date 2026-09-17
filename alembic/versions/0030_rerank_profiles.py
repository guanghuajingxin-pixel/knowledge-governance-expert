"""add rerank_profiles table

Rerank 重排模型改为多条配置（只能生效一条）：
生效配置回写旧版单值 settings（rerank_api_url/rerank_api_key/rerank_model），
kb_common.rag.reranker 运行链路保持不变。

Revision ID: 0030_rerank_profiles
Revises: 0029_sync_source_xxl_job_id
Create Date: 2026-09-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0030_rerank_profiles'
down_revision: Union[str, None] = '0029_sync_source_xxl_job_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rerank_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('api_url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('api_key', sa.Text(), nullable=False, server_default=''),
        sa.Column('model', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('rerank_profiles')
