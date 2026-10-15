"""Wiki knowledge library: wiki pages + generation runs (Karpathy LLM Wiki pattern)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0060_wiki_library"
down_revision = "0059_sync_source_import_once"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("wiki_pages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("library_id", sa.Integer(),
                  sa.ForeignKey("knowledge_libraries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("page_type", sa.String(20), server_default="topic", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(500), server_default="", nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), server_default="STABLE", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("edited_by_human", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("generated_model", sa.String(100), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("library_id", "title", name="uq_wiki_page_library_title"),
    )
    op.create_index("ix_wiki_pages_library_id", "wiki_pages", ["library_id"])
    op.create_table("wiki_generation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("library_id", sa.Integer(),
                  sa.ForeignKey("knowledge_libraries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), server_default="ingest", nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("pages_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pages_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("report", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("triggered_by", sa.String(100), server_default="auto", nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wiki_generation_runs_library_id", "wiki_generation_runs", ["library_id"])


def downgrade():
    op.drop_table("wiki_generation_runs")
    op.drop_table("wiki_pages")
