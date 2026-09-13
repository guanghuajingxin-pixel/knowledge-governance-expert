"""流水线配置仅作为表单数据读取，不执行其中的节点或说明文字。"""
import hashlib
import json
import math

import yaml


def normalize_variables(raw, node_id: str | None = None) -> list[dict]:
    if isinstance(raw, list):
        raw = {item["variable"]: item for item in raw if isinstance(item, dict) and item.get("variable")}
    if not isinstance(raw, dict):
        return []
    variables = []
    for key, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        owner = meta.get("belong_to_node_id")
        if node_id and owner and owner not in ("shared", node_id):
            continue
        variables.append({
            "variable": meta.get("variable") or key, "label": meta.get("label") or key,
            "type": meta.get("type") or "text-input", "required": bool(meta.get("required")),
            "default_value": meta.get("default_value"), "options": meta.get("options") or [],
            "unit": meta.get("unit") or "", "tooltips": meta.get("tooltips") or "",
            "max_length": meta.get("max_length"),
        })
    return variables


def apply_inputs(variables: list[dict], inputs: dict) -> dict:
    if not isinstance(inputs, dict):
        raise ValueError("流水线参数必须是 JSON 对象")
    if not variables:
        return inputs.copy()
    resolved = {}
    for item in variables:
        key, label = item["variable"], item["label"]
        value = inputs.get(key, item.get("default_value"))
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            if item["required"]:
                raise ValueError(f"请填写流水线必填参数：{label}")
            continue
        kind = item["type"]
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"{label} 必须为数字")
        if kind == "checkbox" and not isinstance(value, bool):
            raise ValueError(f"{label} 必须为开关值")
        if kind == "select" and value not in item["options"]:
            raise ValueError(f"{label} 的选项无效")
        if kind in ("text-input", "paragraph") and not isinstance(value, str):
            raise ValueError(f"{label} 必须为文本")
        if kind in ("text-input", "paragraph") and item.get("max_length") and len(value) > int(item["max_length"]):
            raise ValueError(f"{label} 超过允许的文本长度")
        resolved[key] = value
    return resolved


def parse_pipeline(content: bytes, node_id: str) -> dict:
    if len(content) > 1024 * 1024:
        raise ValueError("流水线配置文件不得超过 1 MB")
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict) or data.get("kind") != "rag_pipeline":
            raise ValueError("请选择 Dify 导出的 .pipeline 配置文件")
        workflow = data["workflow"]
        nodes = workflow["graph"]["nodes"]
        node = next((n for n in nodes if str(n.get("id")) == node_id), None)
        if not node or node["data"].get("provider_type") != "local_file":
            raise ValueError("配置文件的本地文件节点与目标库已发布节点不匹配，请重新导出该知识库配置")
        return {"node_id": node_id, "variables": normalize_variables(workflow.get("rag_pipeline_variables"), node_id),
                "name": data.get("rag_pipeline", {}).get("name", ""),
                "extensions": node["data"].get("fileExtensions") or []}
    except (yaml.YAMLError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("无法读取流水线配置，请使用 Dify 导出的 .pipeline 文件") from exc


def schema_key(base_url: str, dataset_id: str) -> str:
    return "dify_pipeline_schema:" + hashlib.sha256(f"{base_url.rstrip('/')}:{dataset_id}".encode()).hexdigest()[:40]


def saved_schema(db, base_url: str, dataset_id: str) -> dict | None:
    from kb_common.models import Setting
    row = db.get(Setting, schema_key(base_url, dataset_id))
    return json.loads(row.value) if row else None
