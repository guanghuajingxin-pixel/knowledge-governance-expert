"""add sync tables (sources/runs/mappings/failures/logs)

合并自 DingDingKonwledgePipeline:钉钉知识库 → Dify 增量同步功能。
SyncSource 表自带 cron 字段(每个同步源即一个定时任务),不保留独立 jobs 表。

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_sources',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('workspace_id', sa.String(length=128), nullable=False),
        sa.Column('root_node_id', sa.String(length=128), nullable=False),
        sa.Column('start_dir', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('dify_dataset_name', sa.String(length=200), nullable=False),
        sa.Column('dify_dataset_id', sa.String(length=64), nullable=True),
        sa.Column('delete_policy', sa.String(length=10), nullable=False, server_default='keep'),
        # 每个同步源自带 cron,默认每日 02:00 执行一次
        sa.Column('cron', sa.String(length=120), nullable=False, server_default='0 2 * * *'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sync_sources_enabled', 'sync_sources', ['enabled'])

    op.create_table(
        'sync_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_id', sa.Integer(),
                  sa.ForeignKey('sync_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False, server_default='manual'),
        # running | success | partial | failed
        sa.Column('status', sa.String(length=20), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deleted_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('ix_sync_runs_source_id', 'sync_runs', ['source_id'])
    op.create_index('ix_sync_runs_started_at', 'sync_runs', ['started_at'])

    op.create_table(
        'sync_document_mappings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_id', sa.Integer(),
                  sa.ForeignKey('sync_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(length=128), nullable=False),
        sa.Column('parent_node_id', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('relative_path', sa.String(length=1000), nullable=False, server_default=''),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('meta_hash', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('content_hash', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('local_path', sa.String(length=1000), nullable=False, server_default=''),
        sa.Column('dify_document_id', sa.String(length=64), nullable=True),
        sa.Column('dify_batch', sa.String(length=64), nullable=True),
        # pending | synced | error
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('source_id', 'node_id', name='uq_sync_source_node'),
    )
    op.create_index('ix_sync_document_mappings_source_id', 'sync_document_mappings', ['source_id'])
    op.create_index('ix_sync_document_mappings_status', 'sync_document_mappings', ['status'])

    op.create_table(
        'sync_failures',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.Integer(),
                  sa.ForeignKey('sync_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_id', sa.Integer(),
                  sa.ForeignKey('sync_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(length=128), nullable=True),
        sa.Column('name', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('error', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sync_failures_run_id', 'sync_failures', ['run_id'])
    op.create_index('ix_sync_failures_source_id', 'sync_failures', ['source_id'])

    op.create_table(
        'sync_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.Integer(),
                  sa.ForeignKey('sync_runs.id', ondelete='CASCADE'), nullable=True),
        sa.Column('level', sa.String(length=10), nullable=False, server_default='INFO'),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sync_logs_run_id', 'sync_logs', ['run_id'])
    op.create_index('ix_sync_logs_created_at', 'sync_logs', ['created_at'])


def downgrade() -> None:
    op.drop_table('sync_logs')
    op.drop_table('sync_failures')
    op.drop_table('sync_document_mappings')
    op.drop_table('sync_runs')
    op.drop_table('sync_sources')
