"""add llm_profiles table

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False, server_default='custom'),
        sa.Column('base_url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('api_key', sa.Text(), nullable=False, server_default=''),
        sa.Column('models', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('llm_profiles')
