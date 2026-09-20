"""ragflow_profiles 多配置表（多环境切换，只能生效一条）

Revision ID: 0032_ragflow_profiles
Revises: 0031_structured_processing
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0032_ragflow_profiles"
down_revision = "0031_structured_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ragflow_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ragflow_profiles")
