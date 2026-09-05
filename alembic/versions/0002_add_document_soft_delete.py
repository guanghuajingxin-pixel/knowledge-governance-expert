"""add document soft delete

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('documents', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('idx_documents_is_deleted', 'documents', ['is_deleted'])


def downgrade() -> None:
    op.drop_index('idx_documents_is_deleted', table_name='documents')
    op.drop_column('documents', 'deleted_at')
    op.drop_column('documents', 'is_deleted')
