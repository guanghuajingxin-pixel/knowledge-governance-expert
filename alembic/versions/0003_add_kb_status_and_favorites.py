"""add kb status and favorites

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. knowledge_bases.status
    op.add_column('knowledge_bases',
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default=sa.text("'FULLY_PUBLISHED'")))

    # 2. kb_favorites table
    op.create_table('kb_favorites',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'kb_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('kb_favorites')
    op.drop_column('knowledge_bases', 'status')
