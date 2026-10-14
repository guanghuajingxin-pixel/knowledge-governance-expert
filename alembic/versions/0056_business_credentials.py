"""Business system push credentials (AK/SK) for knowledge sources."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0056_business_credentials"
down_revision = "0055_faq_similar_questions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("business_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.Integer(),
                  sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_key_id", sa.String(64), nullable=False),
        sa.Column("secret_cipher", sa.Text(), nullable=False),
        sa.Column("library_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", name="uq_business_credential_source"),
        sa.UniqueConstraint("access_key_id", name="uq_business_credential_access_key"))
    op.create_index("ix_business_credentials_source_id", "business_credentials", ["source_id"])
    op.create_index("ix_business_credentials_access_key_id", "business_credentials", ["access_key_id"])


def downgrade():
    op.drop_table("business_credentials")
