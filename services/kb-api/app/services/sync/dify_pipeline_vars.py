"""读取 Dify 流水线的 input form 变量定义（分段参数 schema）。

Dify 的 Service API（Dataset API Key 那套）只暴露 4 个流水线路由
（datasource-plugins / datasource node run / pipeline run / file-upload），
**不暴露** 流水线的 input form 变量定义。而 pipeline/run 的 inputs 必须携带
流水线定义的必填变量，缺失会报 500 "xxx is required in input form"。

变量 schema 存在 Dify 自身数据库的 workflows.rag_pipeline_variables 字段
（JSON 对象：{key: {type, label, default_value, required, options, unit, tooltips}}），
关联链：datasets.pipeline_id → pipelines.workflow_id → workflows.rag_pipeline_variables。

本模块用独立 SQLAlchemy 引擎只读查询 Dify DB（配置项 dify_db_url），
供前端自动生成「流水线分段参数」配置表单。未配置 Dify DB 时，读取平台
保存的 .pipeline 参数定义；两者均不可用时允许填写 JSON。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import create_engine, text

from kb_common.config import get_settings

logger = logging.getLogger(__name__)

# 引擎缓存：避免每次请求都建连接池
_engines: dict[str, Any] = {}

_QUERY = text("""
    SELECT w.rag_pipeline_variables
    FROM datasets d
    JOIN pipelines p ON p.id = d.pipeline_id
    JOIN workflows w ON w.id = p.workflow_id
    WHERE d.id = :dataset_id
      AND w.version != 'draft'
    ORDER BY w.created_at DESC
    LIMIT 1
""")


def _engine():
    url = (get_settings().dify_db_url or "").strip()
    if not url:
        return None
    if url not in _engines:
        # pool_pre_ping：Dify 容器重启后连接失效时自动重连
        _engines[url] = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)
    return _engines[url]


def pipeline_form(dataset_id: str, start_node_id: str | None = None) -> dict:
    from .pipeline_schema import normalize_variables, saved_schema
    try:
        engine = _engine()
        if engine is not None:
            with engine.connect() as conn:
                raw = conn.execute(_QUERY, {"dataset_id": dataset_id}).scalar()
            if raw is not None:
                variables = json.loads(raw) if isinstance(raw, str) else raw
                return {"configured": True, "schema_source": "published",
                        "variables": normalize_variables(variables, start_node_id)}
    except Exception:
        logger.warning("读取 Dify 已发布输入表单失败 dataset=%s", dataset_id)
    try:
        from .sync_database import SyncSessionLocal
        from .sync_settings import load_sync_settings
        with SyncSessionLocal() as db:
            schema = saved_schema(db, load_sync_settings(db)["dify_base_url"], dataset_id)
        if schema and schema["node_id"] == start_node_id:
            return {"configured": True, "schema_source": "imported", "variables": schema["variables"]}
    except Exception:
        logger.warning("读取已导入输入表单失败 dataset=%s", dataset_id)
    return {"configured": False, "schema_source": "unavailable", "variables": []}


def fetch_pipeline_variables(dataset_id: str, start_node_id: str | None = None) -> list[dict[str, Any]]:
    return pipeline_form(dataset_id, start_node_id)["variables"]


def resolve_pipeline_inputs(dataset_id: str, node_id: str, inputs: dict) -> dict:
    from .pipeline_schema import apply_inputs
    return apply_inputs(fetch_pipeline_variables(dataset_id, node_id), inputs)


def prepare_inputs_for_dataset(dataset_id: str, inputs: dict | None) -> dict:
    from kb_common.clients.dify_document import dataset_runtime
    from .sync_database import SyncSessionLocal
    from .sync_settings import make_dify_client
    with SyncSessionLocal() as db:
        client = make_dify_client(db)
        try:
            dataset = client.resolve_dataset(dataset_id)
            if dataset_runtime(dataset) != "rag_pipeline":
                return {}
            return resolve_pipeline_inputs(dataset_id, client.local_file_node_id(dataset_id), inputs or {})
        finally:
            client.close()
