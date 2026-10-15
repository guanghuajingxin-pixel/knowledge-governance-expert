"""SyncSource: import_once flag for one-shot dingtalk imports via sync queue."""
from alembic import op
import sqlalchemy as sa

revision = "0059_sync_source_import_once"
down_revision = "0058_dt_folder_is_link"
branch_labels = None
depends_on = None


def upgrade():
    # 存量源均为周期/手动同步源，默认 false
    op.add_column("sync_sources",
                  sa.Column("import_once", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade():
    op.drop_column("sync_sources", "import_once")
