"""add qa_feedbacks and chat_messages.detail

问答反馈表（点赞/纠错/没找到）+ 消息表新增 detail 列（回答链路/召回片段 JSON）。

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('detail', postgresql.JSON(), nullable=True))

    op.create_table(
        'qa_feedbacks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('feedback_type', sa.String(length=20), nullable=False),
        sa.Column('knowledge_title', sa.String(length=500), nullable=True),
        sa.Column('error_type', sa.String(length=32), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('question', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('handler_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('handler_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_qa_feedbacks_user_id', 'qa_feedbacks', ['user_id'])
    op.create_index('ix_qa_feedbacks_session_id', 'qa_feedbacks', ['session_id'])
    op.create_index('ix_qa_feedbacks_message_id', 'qa_feedbacks', ['message_id'])
    op.create_index('ix_qa_feedbacks_feedback_type', 'qa_feedbacks', ['feedback_type'])
    op.create_index('ix_qa_feedbacks_status', 'qa_feedbacks', ['status'])
    op.create_index('ix_qa_feedbacks_created_at', 'qa_feedbacks', ['created_at'])


def downgrade() -> None:
    op.drop_table('qa_feedbacks')
    op.drop_column('chat_messages', 'detail')
