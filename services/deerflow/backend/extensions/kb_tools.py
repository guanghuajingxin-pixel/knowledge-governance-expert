"""企业知识库检索工具（DeerFlow 扩展工具）。

DeerFlow Lead Agent / Sub-Agent 通过本工具访问知识治理平台 kb-api
背后的 Dify 知识库，实现基于企业内部资料的可信问答与引用溯源。

运行时上下文（数据集选择等）由 qa_server 按 thread_id 注入 RUNTIME_CTX，
工具通过 LangChain 注入的 RunnableConfig 获取 thread_id。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

#: thread_id -> {"dataset_ids": list[str], "top_k": int}
RUNTIME_CTX: dict[str, dict[str, Any]] = {}


def _kb_api_url() -> str:
    return os.getenv("KB_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Internal-Token": os.getenv("KB_INTERNAL_TOKEN", ""),
    }


@tool("knowledge_search", parse_docstring=True)
def knowledge_search_tool(query: str, top_k: int = 8, config: RunnableConfig = None) -> str:
    """检索企业内部知识库，涵盖管理制度、流程规范、产品技术文档、审批规则、
    操作手册等公司内部资料。

    使用规则：
    - 凡涉及公司内部信息的问题，必须先调用本工具检索，再严格依据召回内容回答，
      不得编造知识库中不存在的信息；
    - 回答中引用召回内容时，用 [1][2] 形式标注对应的 ref 序号；
    - 一次调用只传一个检索词；复杂/多方面问题应拆分成多个检索词，
      分多次调用（可并行），最后综合各次结果作答；
    - 若召回结果与问题无关，可换一种表述再次检索；仍无结果时明确告知
      “知识库中暂未检索到相关内容”，不要强行作答。

    Args:
        query: 检索词，使用简洁、能命中文档的关键词或问句。
        top_k: 召回段落数量，默认 8，最多 15。
    """
    cfg = (config or {}).get("configurable", {}) or {}
    thread_id = cfg.get("thread_id", "default")
    ctx = RUNTIME_CTX.get(thread_id, {})
    dataset_ids = ctx.get("dataset_ids") or []
    effective_top_k = min(max(int(top_k or 8), 1), 15)

    payload: dict[str, Any] = {
        "query": query,
        "dataset_ids": dataset_ids,
        "top_k": effective_top_k,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{_kb_api_url()}/api/v1/internal/kb/retrieve",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001 - 工具异常需回传给 Agent 处理
        logger.warning("knowledge_search failed: %s", e)
        return json.dumps(
            {"error": f"知识库检索失败：{e.__class__.__name__}，请稍后重试或换个检索词", "results": []},
            ensure_ascii=False,
        )

    hits = data.get("results") or []
    slim = [
        {
            "ref": i + 1,
            "document_title": h.get("document_title") or "未知文档",
            "page_number": h.get("page_number"),
            "score": round(float(h.get("score") or 0.0), 3),
            "content": (h.get("content") or "")[:1200],
        }
        for i, h in enumerate(hits)
    ]
    return json.dumps(
        {"count": len(slim), "results": slim},
        ensure_ascii=False,
        indent=1,
    )


@tool("dingtalk_search", parse_docstring=True)
def dingtalk_search_tool(query: str, top_k: int = 10, config: RunnableConfig = None) -> str:
    """检索钉钉知识库中的文档，按文件名和目录路径做关键词匹配。

    钉钉知识库是企业知识的两个指定检索来源之一，与 knowledge_search（Dify 知识库）
    并列。回答涉及公司内部信息的问题时，应主动检索本工具，无需征得用户同意。
    钉钉知识库支持文档、表格、演示文稿等文件类型，按文件名/目录路径关键词匹配
    （非语义检索），返回文件元数据（名称、所属知识库、目录、链接）。

    使用规则：
    - 与 knowledge_search 配合使用：同一问题先检索 Dify 获取正文内容，
      再检索钉钉发现 Dify 未收录的相关文档；
    - 检索词使用能命中文档名的关键词，多个词空格分隔（全部需命中）；
      结果不理想时换同义词/上位词再次检索；
    - 返回的是文件元数据而非正文：在答案末尾以"可参阅"形式列出文档名和链接，
      答案主体仍基于 knowledge_search 的正文内容组织。

    Args:
        query: 检索关键词，多个词以空格分隔。
        top_k: 返回结果数，默认 10。
    """
    cfg = (config or {}).get("configurable", {}) or {}
    thread_id = cfg.get("thread_id", "default")

    payload: dict[str, Any] = {
        "query": query,
        "top_k": min(max(int(top_k or 10), 1), 30),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_kb_api_url()}/api/v1/internal/dingtalk/search",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk_search failed: %s", e)
        return json.dumps(
            {"error": f"钉钉知识库检索失败：{e.__class__.__name__}", "results": []},
            ensure_ascii=False,
        )

    if data.get("error"):
        err = data["error"]
        # 钉钉未配置/配置失败：告知智能体该来源不可用，直接基于 Dify 结果作答，无需重试
        if "未配置" in err or "配置" in err:
            return json.dumps(
                {"error": f"钉钉知识库暂不可用（{err}），请直接基于 knowledge_search 的结果作答，不要再调用本工具。",
                 "results": []},
                ensure_ascii=False,
            )
        return json.dumps(
            {"error": err, "results": [], "loading": data.get("loading", False)},
            ensure_ascii=False,
        )

    # 钉钉文件列表首次加载中（后台拉取）：提示稍后可换关键词重试
    if data.get("loading"):
        return json.dumps(
            {"note": "钉钉知识库文件列表正在后台同步中，本次暂无结果；可换关键词稍后再试一次。",
             "results": [], "loading": True},
            ensure_ascii=False,
        )

    hits = data.get("results") or []
    slim = [
        {
            "ref": i + 1,
            "title": h.get("title") or "",
            "directory": h.get("directory") or "",
            "workspace": h.get("workspace") or "",
            "url": h.get("url") or "",
            "extension": h.get("extension") or "",
            "creator": h.get("creator") or "",
        }
        for i, h in enumerate(hits)
    ]
    return json.dumps(
        {"count": len(slim), "results": slim},
        ensure_ascii=False,
        indent=1,
    )


@tool("dingtalk_browse", parse_docstring=True)
def dingtalk_browse_tool(action: str, directory: str = "", top_k: int = 30, config: RunnableConfig = None) -> str:
    """浏览钉钉知识库的目录结构与目录下文档（元数据），用于"先定位目录、再逐篇精读"的检索策略。

    两个动作：
    - action="map"：返回各知识库（workspace）及其 2 级目录的文档数量、在线文档数量。
      回答复杂/不确定归属的问题时，**先调用 map 预判**答案最可能落在哪个知识库/目录，
      再用 list 列该目录文档，避免盲目关键词检索。
    - action="list"：按 directory 关键词（目录路径或知识库名的一部分）列出该目录下文档，
      **在线文档（adoc/md/txt，可秒读正文）排在最前**，办公文档（docx/pdf/xlsx，需下载解析）其次。

    使用规则：
    - 问题主题明确但 dingtalk_search 关键词命中率低时，优先 map → list → read_doc；
    - list 结果含 node_id/extension/title，配合 dingtalk_read_doc 逐篇读取；
    - 每读完一篇文档，立即判断其内容能否回答用户问题：能答就停止扩展并作答，不能答再读下一篇，
      不要无差别顺序读取全部文档。

    Args:
        action: "map" 返回目录地图；"list" 列出目录下文档。
        directory: action="list" 时的目录关键词（目录路径或知识库名片段），如 "差旅"、"财务"。
        top_k: list 时最多返回文档数，默认 30。
    """
    payload: dict[str, Any] = {
        "action": action if action in ("map", "list") else "map",
        "directory": directory or "",
        "top_k": min(max(int(top_k or 30), 1), 50),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_kb_api_url()}/api/v1/internal/dingtalk/browse",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk_browse failed: %s", e)
        return json.dumps(
            {"error": f"钉钉目录浏览失败：{e.__class__.__name__}", "results": []},
            ensure_ascii=False,
        )

    if data.get("error"):
        return json.dumps({"error": data["error"], "results": [], "loading": data.get("loading", False)},
                          ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False, indent=1)


@tool("dingtalk_read_doc", parse_docstring=True)
def dingtalk_read_doc_tool(node_id: str, title: str = "", extension: str = "", config: RunnableConfig = None) -> str:
    """读取钉钉知识库中某篇文档的正文内容（Markdown 格式）。

    dingtalk_search 只返回文件元数据（文件名/链接），要获取文档正文必须调用本工具。
    在线文档直接读取 Markdown；二进制文件（docx/pdf/xlsx 等）下载后由平台解析为 Markdown。

    使用规则：
    - 调用本工具前应先通过 dingtalk_search 找到目标文档的 node_id、extension；
    - 回答涉及钉钉文档内容时，**必须**先调用本工具读取正文，再基于正文作答，
      不能仅根据文件名猜测内容或只给文档链接；
    - 同一问题可读取多篇钉钉文档，逐篇读取后综合；
    - 文档较长时，内容会被截断，可聚焦与问题相关的部分。

    Args:
        node_id: 钉钉文档节点 ID（来自 dingtalk_search 的 results[].node_id，必填）。
        title: 文档标题（来自 dingtalk_search 的 results[].title），可选。
        extension: 文档扩展名（来自 dingtalk_search 的 results[].extension），如 docx/pdf/adoc，可选。
    """
    payload: dict[str, Any] = {
        "node_id": node_id,
        "title": title or "",
        "extension": extension or "",
    }
    try:
        with httpx.Client(timeout=600.0) as client:
            resp = client.post(
                f"{_kb_api_url()}/api/v1/internal/dingtalk/content",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk_read_doc failed: %s", e)
        return json.dumps(
            {"error": f"钉钉文档读取失败：{e.__class__.__name__}，可能无权限或文档类型不支持", "content": ""},
            ensure_ascii=False,
        )

    content = data.get("content") or ""
    # 截断过长内容，避免超出上下文（保留首尾，删除中间）
    max_chars = 8000
    if len(content) > max_chars:
        head = content[: max_chars // 2]
        tail = content[-max_chars // 2 :]
        content = f"{head}\n\n...[内容过长已截断]...\n\n{tail}"

    return json.dumps(
        {
            "title": data.get("title") or title,
            "node_id": node_id,
            "content": content,
            "format": data.get("format", "markdown"),
            "url": data.get("url") or "",
        },
        ensure_ascii=False,
        indent=1,
    )
