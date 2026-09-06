"""add operate_metric_records

运营看板指标流水表：每日 0 点定时（或手动刷新）写入，展示取各指标最新一条。

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'operate_metric_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('metric_key', sa.String(length=32), nullable=False),
        sa.Column('metric_date', sa.Date(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('trigger', sa.String(length=16), nullable=False, server_default='daily'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_operate_metric_records_metric_key', 'operate_metric_records', ['metric_key'])
    op.create_index('ix_operate_metric_records_metric_date', 'operate_metric_records', ['metric_date'])
    op.create_index('ix_operate_metric_records_created_at', 'operate_metric_records', ['created_at'])


def downgrade() -> None:
    op.drop_table('operate_metric_records')
