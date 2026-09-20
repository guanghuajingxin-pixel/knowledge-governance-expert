"""Merge heads: library creator + library document tags (tags 已含 timestamps)."""
from alembic import op  # noqa: F401

revision = "0039_merge_library_heads"
down_revision = ("0038_library_creator", "0039_library_document_tags")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
