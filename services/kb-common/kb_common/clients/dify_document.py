"""单文件和目录采集共用的 Dify 文件协议；不转换源文件。"""
from typing import Any


def dataset_runtime(dataset: dict) -> str:
    # 兼容只返回 pipeline_id 的 Dify 版本，不能回落到普通索引接口。
    mode = (dataset.get("runtime_mode") or "").strip()
    if mode == "rag_pipeline" or dataset.get("pipeline_id"):
        return "rag_pipeline"
    if mode not in ("", "general"):
        raise ValueError(f"不支持的 Dify 知识库运行模式：{mode}")
    return "general"


def file_payload(dataset: dict, language: str = "Chinese") -> dict:
    payload = {
        "indexing_technique": dataset.get("indexing_technique") or "high_quality",
        "doc_form": dataset.get("doc_form") or dataset.get("chunk_structure") or "text_model",
        "doc_language": language,
    }
    if not dataset.get("document_count") and payload["doc_form"] == "text_model":
        payload["process_rule"] = {"mode": "automatic"}
    return payload


def pipeline_payload(node_id: str, reference: str, name: str, inputs: dict | None) -> dict:
    return {
        "inputs": inputs if inputs is not None else {},
        "datasource_type": "local_file",
        "datasource_info_list": [{"reference": reference, "name": name}],
        "start_node_id": node_id,
        "is_published": True,
        "response_mode": "blocking",
    }


def pipeline_result(result: dict, filename: str) -> dict[str, Any]:
    documents = result.get("documents") or []
    batch = result.get("batch") or ""
    if documents:
        document = dict(documents[0])
    else:
        data = result.get("data") or {}
        status = data.get("status")
        if status and status != "succeeded":
            raise ValueError(f"Dify 流水线执行失败：{data.get('error') or status}")
        outputs = data.get("outputs") or {}
        document = {"id": outputs.get("document_id"),
                    "name": outputs.get("document_name"),
                    "indexing_status": outputs.get("display_status") or "indexing"}
        batch = batch or outputs.get("batch") or ""
    if not document.get("id"):
        raise ValueError("Dify 流水线未返回 document_id，请确认末尾包含『知识索引』节点并已发布。")
    if document.get("indexing_status") == "error" or document.get("error"):
        raise ValueError(f"Dify 流水线执行失败：{document.get('error') or '索引失败'}")
    document["id"] = str(document["id"])
    document["name"] = document.get("name") or filename
    document.setdefault("indexing_status", "waiting")
    document.setdefault("data_source_type", "local_file")
    return {"document": document, "batch": str(batch), "runtime_mode": "rag_pipeline"}
