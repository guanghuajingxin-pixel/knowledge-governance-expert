"""add sync_tasks table and sync_runs.operator

知识同步队列：逐文档任务记录（待处理/处理中/已完成 + 失败任务级重试）。
同步引擎在运行开始时为本轮将处理的文档预建 pending 行，逐文档流转
running → success | failed；删除类动作记 action=delete。
sync_runs.operator 记录触发人（定时=系统，手动=用户名），任务行继承展示。

Revision ID: 0026_sync_tasks
Revises: 0025_knowledge_libraries
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0026_sync_tasks'
down_revision: Union[str, None] = '0025_knowledge_libraries'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('run_id', sa.Integer(), sa.ForeignKey('sync_runs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('sync_sources.id', ondelete='CASCADE'), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='sync'),
        sa.Column('action', sa.String(length=20), nullable=False, server_default='create'),
        sa.Column('node_id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('file_ext', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('dataset_id', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('dataset_name', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('trigger', sa.String(length=20), nullable=False, server_default='manual'),
        sa.Column('operator', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sync_tasks_status', 'sync_tasks', ['status'])
    op.create_index('ix_sync_tasks_run_id', 'sync_tasks', ['run_id'])
    op.create_index('ix_sync_tasks_source_id', 'sync_tasks', ['source_id'])
    op.add_column('sync_runs', sa.Column('operator', sa.String(length=100), nullable=False, server_default=''))
    # 任务级重试产生的失败记录不归属任何同步运行，run_id 放开为可空。
    op.alter_column('sync_failures', 'run_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('sync_failures', 'run_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('sync_runs', 'operator')
    op.drop_index('ix_sync_tasks_source_id', table_name='sync_tasks')
    op.drop_index('ix_sync_tasks_run_id', table_name='sync_tasks')
    op.drop_index('ix_sync_tasks_status', table_name='sync_tasks')
    op.drop_table('sync_tasks')
