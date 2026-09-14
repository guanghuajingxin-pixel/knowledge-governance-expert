"""add masking policies / exemptions / logs tables

检索返回脱敏策略控制台：masking_policies（条件→识别→动作→执行节点→兜底）、
masking_exemptions（人+范围+实体类型+有效期豁免）、masking_logs（审计，日志自身脱敏）。

Revision ID: 0028_masking_policies
Revises: 0027_sensitive_items
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0028_masking_policies'
down_revision: Union[str, None] = '0027_sensitive_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'masking_policies',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('scope_type', sa.String(length=16), nullable=False, server_default='global'),
        sa.Column('scope_id', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('user_roles', sa.JSON(), nullable=False),
        sa.Column('scenes', sa.JSON(), nullable=False),
        sa.Column('regex_rules', sa.JSON(), nullable=False),
        sa.Column('dict_types', sa.JSON(), nullable=False),
        sa.Column('context_rules', sa.JSON(), nullable=False),
        sa.Column('actions', sa.JSON(), nullable=False),
        sa.Column('pre_llm_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('post_output_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('failure_strategy', sa.String(length=20), nullable=False, server_default='non_sensitive'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_masking_policies_enabled', 'masking_policies', ['enabled'])

    op.create_table(
        'masking_exemptions',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope_type', sa.String(length=16), nullable=False, server_default='global'),
        sa.Column('scope_id', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('entity_types', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('granted_by', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_masking_exemptions_user_id', 'masking_exemptions', ['user_id'])

    op.create_table(
        'masking_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('scene', sa.String(length=20), nullable=False),
        sa.Column('node', sa.String(length=20), nullable=False),
        sa.Column('query', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('policy_ids', sa.JSON(), nullable=False),
        sa.Column('rule_hits', sa.JSON(), nullable=False),
        sa.Column('masked_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('exempted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_masking_logs_created_at', 'masking_logs', ['created_at'])


def downgrade() -> None:
    op.drop_table('masking_logs')
    op.drop_table('masking_exemptions')
    op.drop_index('ix_masking_policies_enabled', table_name='masking_policies')
    op.drop_table('masking_policies')
