"""add qa_feedbacks.knowledge_url

纠错工单增加知识链接字段（钉钉文档/Dify/预览URL），供纠错列表点击跳转原文。

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('qa_feedbacks', sa.Column('knowledge_url', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column('qa_feedbacks', 'knowledge_url')
