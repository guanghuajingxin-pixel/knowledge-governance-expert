"""add sync_sources.xxl_job_id

定时同步调度切换到 XXL-Job：本平台同步源为作业配置唯一事实源，
后端经 admin API 自动增删改对应 XXL-Job 作业，作业 ID 回存本列便于幂等同步。

Revision ID: 0029_sync_source_xxl_job_id
Revises: 0028_masking_policies
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0029_sync_source_xxl_job_id'
down_revision: Union[str, None] = '0028_masking_policies'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sync_sources', sa.Column('xxl_job_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('sync_sources', 'xxl_job_id')
