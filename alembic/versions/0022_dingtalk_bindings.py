"""add dingtalk_bindings

钉钉身份 ↔ 本地用户绑定表：H5 微应用免登与机器人消息归因共用。
首次免登自动建档（users.username=dd_{dt_userid}、role=viewer），
绑定表记录 corp/userid/unionid 与钉钉真实姓名。(corp_id, dt_userid) 唯一。

Revision ID: 0022
Revises: 0021_sync_source_pipeline_inputs
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0022_dingtalk_bindings'
down_revision: Union[str, None] = '0021_sync_source_pipeline_inputs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dingtalk_bindings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('corp_id', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('dt_userid', sa.String(length=128), nullable=False),
        sa.Column('dt_unionid', sa.String(length=128), nullable=True),
        sa.Column('dt_name', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('corp_id', 'dt_userid', name='uq_dingtalk_binding_corp_user'),
    )
    op.create_index('ix_dingtalk_bindings_user_id', 'dingtalk_bindings', ['user_id'],
                    unique=True)


def downgrade() -> None:
    op.drop_index('ix_dingtalk_bindings_user_id', table_name='dingtalk_bindings')
    op.drop_table('dingtalk_bindings')
