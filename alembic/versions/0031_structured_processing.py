"""add structured processing tables (tasks / schemas / write_logs)

知识加工 · 结构化处理：文档经 MinerU 解析得到结构化 JSON 后，
按用户设计的表结构 + 字段映射生成行数据，一键写入共享 PG 的 structured schema。

- structured_tasks      解析任务（文件、引擎、状态、归一化 content JSON）
- structured_schemas    表结构 + 映射设计（目标表、行源、列映射）
- structured_write_logs 写入历史（目标表、行数、状态）

Revision ID: 0031_structured_processing
Revises: 0030_rerank_profiles
Create Date: 2026-09-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0031_structured_processing'
down_revision: Union[str, None] = '0030_rerank_profiles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'structured_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_name', sa.String(length=512), nullable=False),
        sa.Column('file_ext', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('engine', sa.String(length=32), nullable=False, server_default='kit_v1'),
        sa.Column('tier', sa.String(length=32), nullable=False, server_default='standard'),
        sa.Column('ocr_mode', sa.String(length=16), nullable=False, server_default='auto'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('remote_job_id', sa.String(length=128), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('content_json', sa.JSON(), nullable=True),
        sa.Column('markdown', sa.Text(), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_structured_tasks_status', 'structured_tasks', ['status'])

    op.create_table(
        'structured_schemas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('target_table', sa.String(length=128), nullable=False),
        sa.Column('row_source', sa.String(length=256), nullable=False, server_default='content'),
        sa.Column('columns', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'structured_write_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('schema_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('target_table', sa.String(length=128), nullable=False),
        sa.Column('rows_written', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='success'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['schema_id'], ['structured_schemas.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['structured_tasks.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_structured_write_logs_schema', 'structured_write_logs', ['schema_id'])


def downgrade() -> None:
    op.drop_index('ix_structured_write_logs_schema', table_name='structured_write_logs')
    op.drop_table('structured_write_logs')
    op.drop_table('structured_schemas')
    op.drop_index('ix_structured_tasks_status', table_name='structured_tasks')
    op.drop_table('structured_tasks')
