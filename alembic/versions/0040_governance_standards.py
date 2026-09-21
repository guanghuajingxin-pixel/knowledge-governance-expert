"""治理标准：本地可管理主表 + 版本历史表（支持审核流转与回滚）。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0040_governance_standards"
down_revision = "0039_merge_library_heads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "governance_standards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("code", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.String(32), nullable=False, server_default=""),
        sa.Column("effective_date", sa.String(20), nullable=False, server_default=""),
        sa.Column("link", sa.String(1000), nullable=False, server_default=""),
        sa.Column("maintainer", sa.String(200), nullable=False, server_default=""),
        sa.Column("published_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("latest_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("latest_status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime, server_default=sa.text("now()")),
    )
    op.create_table(
        "governance_standard_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("standard_id", UUID(as_uuid=True),
                  sa.ForeignKey("governance_standards.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("doc_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("code", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.String(32), nullable=False, server_default=""),
        sa.Column("effective_date", sa.String(20), nullable=False, server_default=""),
        sa.Column("link", sa.String(1000), nullable=False, server_default=""),
        sa.Column("maintainer", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", index=True),
        sa.Column("created_by", sa.String(100), nullable=False, server_default=""),
        sa.Column("review_comment", sa.Text, nullable=False, server_default=""),
        sa.Column("reviewed_by", sa.String(100), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()")),
    )


def downgrade():
    op.drop_table("governance_standard_versions")
    op.drop_table("governance_standards")
