"""Persist manual collection results."""
from alembic import op
import sqlalchemy as sa

revision = "0013_collection_transfers"
down_revision = "0012_add_sync_mapping_enabled"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("collection_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("document_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("collection_transfers")
