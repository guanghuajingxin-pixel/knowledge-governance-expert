"""Remove external KB integration (Dify/RAGFlow): drop tables, rename reused columns, purge data.

- 删表：dify_profiles / ragflow_profiles / dify_dingtalk_doc_mappings /
  processed_documents / knowledge_relations / knowledge_tags / collection_transfers
- 删行：knowledge_libraries.library_type='external'、sync_sources.backend_type in (dify,ragflow)、
  knowledge_sources.source_type in (dify_dataset,ragflow_dataset)、settings 的 dify_*/ragflow_* 键
- 重命名：sync_sources.dify_dataset_{name,id} → dataset_{name,id}；
  sync_document_mappings.dify_document_id/dify_batch → document_id/batch_id
- 删列：sync_sources.backend_type / pipeline_inputs
- knowledge_libraries.library_type server_default: external → document
"""
import json
from alembic import op
import sqlalchemy as sa

revision = "0054_remove_external_kb"
down_revision = "0053_chunk_enhance"
branch_labels = None
depends_on = None

_DROPPED_TABLES = (
    "dify_profiles",
    "ragflow_profiles",
    "dify_dingtalk_doc_mappings",
    "processed_documents",
    "knowledge_relations",
    "knowledge_tags",
    "collection_transfers",
)


def _purge_agent_config_libraries(bind) -> None:
    """agent_config.knowledge_library_ids 过滤掉已删除的外部镜像库 ID。"""
    row = bind.execute(
        sa.text("SELECT value FROM settings WHERE key = 'agent_config'")
    ).fetchone()
    if not row:
        return
    try:
        cfg = json.loads(row[0] or "{}")
    except (ValueError, TypeError):
        return
    ids = cfg.get("knowledge_library_ids")
    if not isinstance(ids, list) or not ids:
        return
    kept = [
        i for i in ids
        if bind.execute(
            sa.text("SELECT 1 FROM knowledge_libraries WHERE id = :lid"),
            {"lid": int(i)},
        ).fetchone()
    ]
    if kept == ids:
        return
    cfg["knowledge_library_ids"] = kept
    bind.execute(
        sa.text("UPDATE settings SET value = :v WHERE key = 'agent_config'"),
        {"v": json.dumps(cfg, ensure_ascii=False)},
    )


def upgrade():
    # 1) 清理存量数据（列重命名前，沿用旧列名）
    op.execute("DELETE FROM knowledge_libraries WHERE library_type = 'external'")
    op.execute("DELETE FROM sync_sources WHERE backend_type IN ('dify', 'ragflow')")
    op.execute("DELETE FROM knowledge_sources WHERE source_type IN ('dify_dataset', 'ragflow_dataset')")
    op.execute("DELETE FROM settings WHERE key LIKE 'dify\\_%' ESCAPE '\\' OR key LIKE 'ragflow\\_%' ESCAPE '\\'")
    # 脱敏策略里 scope=library 指向已删镜像库的行一并清理
    op.execute(
        "DELETE FROM masking_policies WHERE scope_type = 'library' "
        "AND scope_id <> '' AND scope_id NOT IN (SELECT CAST(id AS TEXT) FROM knowledge_libraries)"
    )
    _purge_agent_config_libraries(op.get_bind())

    # 2) 重命名被本地库同步复用的列（dify 前缀 → 中性命名）
    with op.batch_alter_table("sync_sources") as batch:
        batch.alter_column("dify_dataset_name", new_column_name="dataset_name")
        batch.alter_column("dify_dataset_id", new_column_name="dataset_id")
        batch.drop_column("backend_type")
        batch.drop_column("pipeline_inputs")
    with op.batch_alter_table("sync_document_mappings") as batch:
        batch.alter_column("dify_document_id", new_column_name="document_id")
        batch.alter_column("dify_batch", new_column_name="batch_id")

    # 3) library_type 默认值对齐本地库语义
    op.execute(
        "ALTER TABLE knowledge_libraries ALTER COLUMN library_type SET DEFAULT 'document'"
    )

    # 4) 下线外部库专有表
    for table in _DROPPED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade():
    # 数据不可恢复，仅还原表结构与列名
    op.create_table("dify_profiles",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("dataset_ids", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("ragflow_profiles",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("dify_dingtalk_doc_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dify_dataset_id", sa.String(64), nullable=False),
        sa.Column("dify_document_id", sa.String(64), nullable=False, unique=True),
        sa.Column("dingtalk_node_id", sa.String(128), nullable=False),
        sa.Column("dingtalk_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("name", sa.String(500), nullable=False, server_default=""),
        sa.Column("method", sa.String(10), nullable=False, server_default="file"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("processed_documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("process_status", sa.String(16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("knowledge_relations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("source_doc_id", sa.String(64), nullable=False),
        sa.Column("target_doc_id", sa.String(64), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_doc_id", "target_doc_id", "relation_type",
                            name="uq_knowledge_relation_triple"))
    op.create_table("knowledge_tags",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("color", sa.String(16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_table("collection_transfers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("document_id", sa.String(128)),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime()))
    op.execute(
        "ALTER TABLE knowledge_libraries ALTER COLUMN library_type SET DEFAULT 'external'"
    )
    with op.batch_alter_table("sync_document_mappings") as batch:
        batch.alter_column("document_id", new_column_name="dify_document_id")
        batch.alter_column("batch_id", new_column_name="dify_batch")
    with op.batch_alter_table("sync_sources") as batch:
        batch.add_column(sa.Column("backend_type", sa.String(16), server_default="dify", nullable=False))
        batch.add_column(sa.Column("pipeline_inputs", sa.Text(), server_default="{}", nullable=False))
        batch.alter_column("dataset_name", new_column_name="dify_dataset_name")
        batch.alter_column("dataset_id", new_column_name="dify_dataset_id")
