"""知识加工服务：对已进入 Dify 的文档进行 AI 打标、摘要生成、知识关系构建，
并提供上下文扩展接口供智能问答调用。

核心能力：
1. fetch_document_content — 从 Dify 拉取文档分块内容
2. enhance_document — LLM 生成标签/摘要/关键词/文档类型
3. build_relations — 对数据集中文档两两构建语义关系
4. expand_context — 问答时利用摘要+关系扩展上下文
"""
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.clients import dify_client, llm_client
from kb_common.models import ProcessedDocument, KnowledgeRelation, KnowledgeTag, Setting
from kb_common.config import get_settings

logger = logging.getLogger(__name__)

# 标签颜色池
TAG_COLORS = ["#409EFF", "#67C23A", "#E6A23C", "#F56C6C", "#909399",
              "#9C27B0", "#00BCD4", "#FF9800", "#3F51B5", "#009688"]

# 关系类型枚举
RELATION_TYPES = ["引用", "相似主题", "因果", "包含", "并列", "前置知识", "依赖", "对比"]


async def _effective(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key, "") or ""


async def _llm_chat(s: AsyncSession, messages: list[dict]) -> str:
    base_url = await _effective(s, "llm_base_url")
    api_key = await _effective(s, "llm_api_key")
    model = await _effective(s, "llm_model")
    return await llm_client.chat(messages, model=model, base_url=base_url, api_key=api_key)


# ============================================================
# 1. 从 Dify 拉取文档内容
# ============================================================

async def fetch_document_content(dataset_id: str, document_id: str,
                                 max_chars: int = 12000) -> tuple[str, str]:
    """从 Dify 获取文档标题和拼接后的分块内容（截断到 max_chars）。"""
    segments = await dify_client.get_document_segments(dataset_id, document_id)
    parts: list[str] = []
    name = document_id
    for seg in segments:
        if isinstance(seg, dict):
            name = seg.get("document", {}).get("name") or name
            content = seg.get("content") or seg.get("text") or ""
            if content:
                parts.append(content)
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（内容已截断）"
    return name, text


# ============================================================
# 2. AI 打标 + 摘要生成
# ============================================================

TAG_SUMMARY_PROMPT = """你是知识治理专家。请阅读以下文档内容，输出结构化的加工结果。

【文档标题】{name}

【文档内容】
{content}

请严格按以下 JSON 格式输出（不要输出 JSON 以外的文字）：
{{
  "tags": ["标签1", "标签2", "标签3"],
  "summary": "200字以内的文档摘要，概括核心内容与适用场景",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "doc_type": "文档类型（如：制度规范/技术文档/产品手册/会议纪要/培训材料/FAQ/其它）"
}}

要求：
- tags：3-6 个最能代表文档主题的标签，使用领域通用词汇
- summary：客观概括，不要照抄原文
- keywords：3-8 个检索关键词
- doc_type：从括号内选择最贴切的一类
"""


async def enhance_document(s: AsyncSession, dataset_id: str, document_id: str) -> dict:
    """对单个文档执行 AI 打标 + 摘要生成，结果写入 processed_documents。"""
    # 获取或创建加工记录
    row = (await s.execute(
        select(ProcessedDocument).where(ProcessedDocument.document_id == document_id)
    )).scalar_one_or_none()

    if not row:
        row = ProcessedDocument(
            id=uuid.uuid4(), dataset_id=dataset_id, document_id=document_id, name=document_id,
        )
        s.add(row)
    row.process_status = "processing"
    row.error_message = ""
    await s.flush()

    try:
        name, content = await fetch_document_content(dataset_id, document_id)
        row.name = name
        if not content.strip():
            row.process_status = "failed"
            row.error_message = "文档内容为空"
            await s.commit()
            return {"status": "failed", "error": "文档内容为空"}

        messages = [
            {"role": "system", "content": "你是知识治理专家，擅长文档打标与摘要。"},
            {"role": "user", "content": TAG_SUMMARY_PROMPT.format(name=name, content=content)},
        ]
        raw = await _llm_chat(s, messages)
        result = _parse_json(raw)

        tags = result.get("tags") or []
        summary = result.get("summary") or ""
        keywords = result.get("keywords") or []
        doc_type = result.get("doc_type") or ""

        row.tags = tags
        row.summary = summary
        row.keywords = keywords
        row.doc_type = doc_type
        row.process_status = "completed"
        await s.flush()

        # 更新标签库计数
        await _upsert_tags(s, tags)
        await s.commit()
        return {
            "status": "completed",
            "document_id": document_id,
            "name": name,
            "tags": tags,
            "summary": summary,
            "keywords": keywords,
            "doc_type": doc_type,
        }
    except Exception as e:
        row.process_status = "failed"
        row.error_message = str(e)[:500]
        await s.commit()
        logger.exception("enhance_document failed for %s", document_id)
        return {"status": "failed", "error": str(e)}


# ============================================================
# 3. 知识关系构建
# ============================================================

RELATION_PROMPT = """你是知识图谱构建专家。请分析以下两篇文档的内容，判断它们之间是否存在知识关联。

【文档 A】{name_a}
{content_a}

【文档 B】{name_b}
{content_b}

请严格按 JSON 输出（不要输出其它文字）：
{{
  "has_relation": true,
  "relation_type": "引用|相似主题|因果|包含|并列|前置知识|依赖|对比|无",
  "weight": 0.0,
  "description": "一句话描述两者关系（如无关系填\"无明显关联\"）"
}}

要求：
- has_relation：判断两者是否有实质关联
- relation_type：从枚举中选择最贴切的；无关联填"无"
- weight：0-1 之间的关联强度，无关联填 0
- description：简洁描述关系
"""


async def build_relations(s: AsyncSession, dataset_id: str) -> dict:
    """对数据集中已加工的文档两两构建语义关系。"""
    docs = (await s.execute(
        select(ProcessedDocument)
        .where(ProcessedDocument.dataset_id == dataset_id,
               ProcessedDocument.process_status == "completed")
        .order_by(ProcessedDocument.updated_at.desc())
    )).scalars().all()

    if len(docs) < 2:
        return {"status": "skipped", "reason": "至少需要 2 篇已加工文档", "created": 0}

    # 限制最多处理 15 篇（约 105 对），避免 LLM 调用爆炸
    docs = docs[:15]
    # 清理该数据集已有关系后重建
    await s.execute(delete(KnowledgeRelation).where(
        KnowledgeRelation.source_doc_id.in_([d.document_id for d in docs])))

    created = 0
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            a, b = docs[i], docs[j]
            try:
                messages = [
                    {"role": "system", "content": "你是知识图谱构建专家。"},
                    {"role": "user", "content": RELATION_PROMPT.format(
                        name_a=a.name, content_a=(a.summary or "")[:3000],
                        name_b=b.name, content_b=(b.summary or "")[:3000],
                    )},
                ]
                raw = await _llm_chat(s, messages)
                result = _parse_json(raw)
                if not result.get("has_relation") or result.get("relation_type") == "无":
                    continue
                rtype = result.get("relation_type") or "相似主题"
                weight = float(result.get("weight") or 0.5)
                desc = result.get("description") or ""
                # 双向存储：A→B 和 B→A
                for src, tgt in [(a.document_id, b.document_id), (b.document_id, a.document_id)]:
                    s.add(KnowledgeRelation(
                        id=uuid.uuid4(), source_doc_id=src, target_doc_id=tgt,
                        relation_type=rtype, weight=weight, description=desc,
                    ))
                created += 1
                await s.flush()
            except Exception as e:
                logger.warning("build_relations pair failed: %s", e)
                continue
    await s.commit()
    return {"status": "completed", "created": created, "doc_count": len(docs)}


# ============================================================
# 4. 上下文扩展（供智能问答调用）
# ============================================================

async def expand_context(s: AsyncSession, document_ids: list[str],
                         query: str, max_related: int = 3) -> dict:
    """根据命中的文档 ID 和查询，利用加工结果扩展问答上下文。

    返回：
    - summaries: 命中文档的摘要（注入 system prompt 提升理解）
    - related: 关联文档列表（用于深度探索）
    - tags: 命中文档的标签聚合（可用于过滤/路由）
    """
    summaries: list[dict] = []
    tags_set: set[str] = set()
    related: list[dict] = []

    if not document_ids:
        return {"summaries": [], "related": [], "tags": []}

    docs = (await s.execute(
        select(ProcessedDocument).where(ProcessedDocument.document_id.in_(document_ids))
    )).scalars().all()
    dmap = {d.document_id: d for d in docs}

    for d in docs:
        summaries.append({
            "document_id": d.document_id,
            "name": d.name,
            "summary": d.summary,
            "tags": d.tags,
            "doc_type": d.doc_type,
        })
        tags_set.update(d.tags)

    # 查关联文档（双向）
    if docs:
        rels = (await s.execute(
            select(KnowledgeRelation)
            .where(KnowledgeRelation.source_doc_id.in_(list(dmap.keys())))
            .order_by(KnowledgeRelation.weight.desc())
            .limit(max_related * 3)
        )).scalars().all()

        seen: set[str] = set(dmap.keys())
        for rel in rels:
            if rel.target_doc_id in seen:
                continue
            seen.add(rel.target_doc_id)
            rel_doc = (await s.execute(
                select(ProcessedDocument).where(ProcessedDocument.document_id == rel.target_doc_id)
            )).scalar_one_or_none()
            if rel_doc:
                related.append({
                    "document_id": rel.target_doc_id,
                    "name": rel_doc.name,
                    "relation_type": rel.relation_type,
                    "weight": rel.weight,
                    "description": rel.description,
                    "summary": rel_doc.summary,
                    "tags": rel_doc.tags,
                })
            if len(related) >= max_related:
                break

    return {
        "summaries": summaries,
        "related": related,
        "tags": sorted(tags_set),
    }


# ============================================================
# 工具函数
# ============================================================

def _parse_json(raw: str) -> dict:
    """从 LLM 输出中解析 JSON（兼容 markdown 代码块包裹）。"""
    text = raw.strip()
    # 去掉 ```json ... ``` 包裹
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取第一个 { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


async def _upsert_tags(s: AsyncSession, tags: list[str]) -> None:
    """将标签写入标签库（不存在则创建，存在则计数+1）。"""
    for i, name in enumerate(tags):
        if not name:
            continue
        name = name.strip()[:64]
        tag = (await s.execute(
            select(KnowledgeTag).where(KnowledgeTag.name == name)
        )).scalar_one_or_none()
        if tag:
            tag.count = (tag.count or 0) + 1
        else:
            s.add(KnowledgeTag(
                id=uuid.uuid4(), name=name,
                color=TAG_COLORS[i % len(TAG_COLORS)], count=1,
            ))
    await s.flush()
