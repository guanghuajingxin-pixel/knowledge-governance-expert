"""检索返回脱敏引擎。

识别（内置正则 + 敏感词典 + 上下文规则 + 自定义正则）
→ 动作（部分遮蔽/泛化/替换/哈希/截断/拒绝，多策略冲突取最严格）
→ 一致性替换（同一实体文本 → 同一确定性令牌，防多片段拼接还原）。

执行节点：
- pre_llm：/internal/kb/retrieve 等送 LLM 前出口（底线，LLM 不接触明文）
- post_output：统一检索结果与问答流式输出的二次过滤
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import SessionLocal
from kb_common.models import MaskingPolicy, MaskingExemption, MaskingLog, SensitiveItem, Setting

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ENTITY_TYPES = ("phone", "id_card", "bank_card", "email", "custom")
ACTIONS = ("partial", "generalize", "replace", "hash", "truncate", "reject")
# 严格度：多策略命中同一实体类型时取最严格
_ACTION_STRICTNESS = {"partial": 1, "generalize": 2, "truncate": 3, "replace": 4, "hash": 5, "reject": 6}

# 内置识别正则（id_card 先于 bank_card 匹配，避免 18 位被吞）
_BUILTIN_REGEX = {
    "id_card": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "bank_card": re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}
ENTITY_LABELS = {"phone": "手机号", "id_card": "身份证", "bank_card": "银行卡",
                 "email": "邮箱", "custom": "敏感信息"}
FAILURE_STRATEGIES = ("block", "non_sensitive", "deny")

# 全局配置（settings 表 key），默认值：总开关开、两个节点都开
GLOBAL_KEY = "masking_global"
GLOBAL_DEFAULTS = {
    "enabled": True,
    "pre_llm": True,
    "post_output": True,
    "failure_strategy": "non_sensitive",
    "hint": "部分内容因权限隐藏",
}

# 词典缓存（敏感词正则跨请求复用，TTL 30s）
_DICT_CACHE: dict[tuple, tuple[float, dict[str, str]]] = {}
_DICT_TTL = 30.0
# 上下文规则：关键词邻近金额识别窗口与金额模式
_CTX_WINDOW = 24
_AMOUNT_RE = re.compile(r"\d[\d,，.]*\s*[万亿kKwW]?元?")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class RuleHit:
    rule: str            # 规则标签（如 内置:手机号 / 词典 / 正则:xx / 上下文:薪酬）
    entity_type: str
    count: int = 0


@dataclass
class MaskContext:
    """一次请求的脱敏上下文：已按场景/角色/作用域筛好的策略与豁免。"""
    policies: list[dict] = field(default_factory=list)   # {id,name,actions:{et:action}}
    dict_words: dict[str, str] = field(default_factory=dict)  # 词条 -> entity_type
    regex_rules: list[dict] = field(default_factory=list)     # {compiled,label,entity_type}
    context_rules: list[dict] = field(default_factory=list)   # {keyword,entity_type}
    exempt_types: set[str] = field(default_factory=set)       # 已豁免实体类型
    actions: dict[str, str] = field(default_factory=dict)     # 合并后最严格动作
    policy_ids: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 全局配置与策略装载
# ---------------------------------------------------------------------------

async def get_global_config(s: AsyncSession) -> dict:
    row = (await s.execute(select(Setting).where(Setting.key == GLOBAL_KEY))).scalar_one_or_none()
    cfg = dict(GLOBAL_DEFAULTS)
    if row and row.value:
        try:
            cfg.update(json.loads(row.value))
        except (ValueError, TypeError):
            pass
    return cfg


async def save_global_config(s: AsyncSession, cfg: dict) -> None:
    from kb_common.models import Setting as _Setting
    row = (await s.execute(select(_Setting).where(_Setting.key == GLOBAL_KEY))).scalar_one_or_none()
    merged = dict(GLOBAL_DEFAULTS)
    if row and row.value:
        try:
            merged.update(json.loads(row.value))
        except (ValueError, TypeError):
            pass
    merged.update({k: v for k, v in cfg.items() if k in GLOBAL_DEFAULTS})
    value = json.dumps(merged, ensure_ascii=False)
    if row:
        row.value = value
    else:
        s.add(_Setting(key=GLOBAL_KEY, value=value, is_secret=False))
    await s.commit()


def _policy_matches(p: MaskingPolicy, scene: str, user_role: str, scope_ids: set[str]) -> bool:
    if not p.enabled:
        return False
    if p.scenes and scene not in (p.scenes or []):
        return False
    if p.user_roles and user_role not in (p.user_roles or []):
        return False
    if p.scope_type == "global":
        return True
    return f"{p.scope_type}:{p.scope_id}" in scope_ids


async def _load_dict_words(s: AsyncSession, types: set[str]) -> dict[str, str]:
    """加载启用的敏感词典词条（词条 -> 实体类型），带 TTL 缓存。"""
    if not types:
        return {}
    key = tuple(sorted(types))
    cached = _DICT_CACHE.get(key)
    if cached and time.time() - cached[0] < _DICT_TTL:
        return cached[1]
    rows = (await s.execute(select(SensitiveItem).where(
        SensitiveItem.enabled == True,  # noqa: E712
        SensitiveItem.type.in_(key),
    ))).scalars().all()
    words = {r.content: r.type for r in rows if r.content.strip()}
    _DICT_CACHE[key] = (time.time(), words)
    return words


async def load_mask_context(
    s: AsyncSession,
    *,
    scene: str,
    user_role: str,
    user_id=None,
    scope_ids: set[str] | None = None,
    node: str = "pre_llm",
) -> MaskContext | None:
    """按场景/角色/作用域装载脱敏上下文；无策略或全局关闭时返回 None（调用方零开销直通）。"""
    cfg = await get_global_config(s)
    if not cfg.get("enabled", True):
        return None
    node_key = "pre_llm" if node == "pre_llm" else "post_output"
    if not cfg.get(node_key, True):
        return None

    from kb_common.models import User
    if user_id is not None and not user_role:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        user_role = (u.role if u else None) or "viewer"

    scopes = scope_ids or set()
    rows = (await s.execute(select(MaskingPolicy).where(
        MaskingPolicy.enabled == True,  # noqa: E712
    ).order_by(MaskingPolicy.priority))).scalars().all()
    matched = [p for p in rows if _policy_matches(p, scene, user_role, scopes)]
    if not matched:
        return None

    ctx = MaskContext()
    dict_types: set[str] = set()
    for p in matched:
        ctx.policies.append({"id": p.id, "name": p.name, "actions": p.actions or {}})
        ctx.policy_ids.append(p.id)
        for et, act in (p.actions or {}).items():
            if et in ENTITY_TYPES and act in ACTIONS:
                cur = ctx.actions.get(et)
                if cur is None or _ACTION_STRICTNESS[act] > _ACTION_STRICTNESS[cur]:
                    ctx.actions[et] = act
        for r in (p.regex_rules or []):
            pat = (r.get("pattern") or "").strip()
            if not pat:
                continue
            try:
                compiled = re.compile(pat)
            except re.error:
                continue  # 非法正则跳过，不阻断整条策略
            ctx.regex_rules.append({
                "compiled": compiled,
                "label": (r.get("label") or "自定义规则")[:50],
                "entity_type": r.get("entity_type") if r.get("entity_type") in ENTITY_TYPES else "custom",
            })
        for r in (p.context_rules or []):
            kw = (r.get("keyword") or "").strip()
            if kw:
                ctx.context_rules.append({
                    "keyword": kw,
                    "entity_type": r.get("entity_type") if r.get("entity_type") in ENTITY_TYPES else "custom",
                })
        dict_types.update(t for t in (p.dict_types or []) if t in ENTITY_TYPES)
    ctx.dict_words = await _load_dict_words(s, dict_types)

    # 豁免：绑定人 + 范围 + 实体类型 + 有效期（到期自动失效）
    if user_id is not None:
        from datetime import datetime
        now = datetime.now()
        ex_rows = (await s.execute(select(MaskingExemption).where(
            MaskingExemption.user_id == user_id,
        ))).scalars().all()
        for e in ex_rows:
            if e.expires_at and e.expires_at < now:
                continue
            if e.scope_type != "global" and f"{e.scope_type}:{e.scope_id}" not in scopes:
                continue
            if not e.entity_types:
                ctx.exempt_types |= set(ENTITY_TYPES)
            else:
                ctx.exempt_types |= {t for t in e.entity_types if t in ENTITY_TYPES}
        if ctx.exempt_types:
            for et in list(ctx.actions):
                if et in ctx.exempt_types:
                    del ctx.actions[et]
            ctx.dict_words = {w: t for w, t in ctx.dict_words.items() if t not in ctx.exempt_types}
            ctx.regex_rules = [r for r in ctx.regex_rules if r["entity_type"] not in ctx.exempt_types]
            ctx.context_rules = [r for r in ctx.context_rules if r["entity_type"] not in ctx.exempt_types]

    if not ctx.actions and not ctx.dict_words and not ctx.regex_rules and not ctx.context_rules:
        return None
    return ctx


# ---------------------------------------------------------------------------
# 识别与动作
# ---------------------------------------------------------------------------

def _action_for(ctx: MaskContext, entity_type: str) -> str | None:
    act = ctx.actions.get(entity_type)
    if act is None and entity_type in ctx.actions.values():
        return "custom"
    return act


def _deterministic_token(entity: str, label: str) -> str:
    """一致性替换令牌：同一实体文本 → 同一令牌（防多片段拼接还原）。"""
    h = hashlib.md5(entity.encode("utf-8")).hexdigest()[:6]
    return f"[{label}#{h}]"


def _apply_action(entity: str, action: str, entity_type: str, label: str) -> str:
    if action == "partial":
        if entity_type == "phone" and len(entity) == 11:
            return f"{entity[:3]}****{entity[-4:]}"
        if entity_type == "id_card" and len(entity) >= 15:
            return f"{entity[:3]}{'*' * (len(entity) - 5)}{entity[-2:]}"
        if entity_type == "bank_card":
            return f"{'*' * (len(entity) - 4)}{entity[-4:]}"
        if entity_type == "email" and "@" in entity:
            name, dom = entity.split("@", 1)
            return f"{name[:1]}***@{dom}"
        return f"{entity[:1]}***"
    if action == "truncate":
        return f"{entity[:2]}***"
    if action == "hash":
        return f"HASH({hashlib.sha256(entity.encode('utf-8')).hexdigest()[:12]})"
    if action == "replace":
        return _deterministic_token(entity, label or ENTITY_LABELS.get(entity_type, "敏感信息"))
    if action == "generalize":
        digits = re.sub(r"\D", "", entity)
        if len(digits) >= 3:  # 数值泛化为数量级区间
            lead = int(digits[0])
            unit = 10 ** (len(digits) - 1)
            return f"{lead * unit}-{(lead + 1) * unit}"
        if entity_type == "custom":
            return f"某{label}" if label and label != "自定义规则" else "某单位"
        return f"{entity[:1]}***"
    # reject 在文本层按整段遮蔽处理；片段级拒绝由 mask_hits 丢弃整条命中
    return "▇▇▇"


def _find_entities(text: str, ctx: MaskContext) -> list[tuple[int, int, str, str, str]]:
    """识别文本中的敏感实体，返回 (start, end, entity, entity_type, label)，重叠取最严格来源。"""
    found: list[tuple[int, int, str, str, str]] = []
    spans: set[tuple[int, int]] = set()

    def _add(start: int, end: int, entity: str, et: str, label: str):
        if (start, end) in spans:
            return
        spans.add((start, end))
        found.append((start, end, entity, et, label))

    # 内置正则（受 actions 管控的实体类型）
    for et, compiled in _BUILTIN_REGEX.items():
        if et not in ctx.actions:
            continue
        for m in compiled.finditer(text):
            _add(m.start(), m.end(), m.group(), et, f"内置:{ENTITY_LABELS[et]}")
    # 自定义正则
    for r in ctx.regex_rules:
        if r["entity_type"] not in ctx.actions and r["entity_type"] not in ("custom",):
            continue
        for m in r["compiled"].finditer(text):
            _add(m.start(), m.end(), m.group(), r["entity_type"], f"正则:{r['label']}")
    # 敏感词典（整词匹配，长词优先）
    if ctx.dict_words:
        words = sorted(ctx.dict_words, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(w) for w in words))
        for m in pattern.finditer(text):
            w = m.group()
            _add(m.start(), m.end(), w, ctx.dict_words[w], "词典")
    # 上下文规则：关键词邻近金额
    for r in ctx.context_rules:
        if r["entity_type"] not in ctx.actions:
            continue
        for m in re.finditer(re.escape(r["keyword"]), text):
            lo, hi = max(0, m.start() - _CTX_WINDOW), min(len(text), m.end() + _CTX_WINDOW)
            window = text[lo:hi]
            for am in _AMOUNT_RE.finditer(window):
                raw = am.group().strip()
                if not re.search(r"\d", raw):
                    continue
                s = lo + am.start() + (len(am.group()) - len(am.group().lstrip()))
                _add(s, s + len(raw), raw, r["entity_type"], f"上下文:{r['keyword']}")
    return sorted(found, key=lambda x: x[0])


def mask_text(text: str, ctx: MaskContext) -> tuple[str, list[RuleHit]]:
    """对文本执行脱敏，返回 (脱敏后文本, 命中规则汇总)。无命中时原样返回。"""
    if not text or not ctx:
        return text, []
    entities = _find_entities(text, ctx)
    if not entities:
        return text, []
    hits: dict[tuple[str, str], RuleHit] = {}
    out: list[str] = []
    last = 0
    for start, end, entity, et, label in entities:
        if start < last:
            continue  # 与前一命中重叠，跳过
        action = ctx.actions.get(et) or "partial"
        out.append(text[last:start])
        out.append(_apply_action(entity, action, et, label))
        last = end
        key = (label, et)
        if key not in hits:
            hits[key] = RuleHit(rule=label, entity_type=et)
        hits[key].count += 1
    out.append(text[last:])
    return "".join(out), list(hits.values())


def mask_hits(hits: list[dict], ctx: MaskContext, text_fields: tuple[str, ...] = ("content", "text")) \
        -> tuple[list[dict], list[dict], list[RuleHit]]:
    """对召回片段列表脱敏：reject 动作丢弃整条命中，其余就地遮蔽/替换。

    返回 (保留的 hits, 逐条命中明细 [{index,title,hits}], 汇总规则命中)。
    同一实体跨片段生成同一令牌（确定性替换），保证多片段一致性。
    """
    kept: list[dict] = []
    detail: list[dict] = []
    merged: dict[tuple[str, str], RuleHit] = {}
    for idx, h in enumerate(hits):
        hit_list: list[RuleHit] = []
        rejected = False
        new_h = dict(h)
        for f in text_fields:
            v = new_h.get(f)
            if not v:
                continue
            entities = _find_entities(v, ctx)
            if not entities:
                continue
            if any((ctx.actions.get(et) or "partial") == "reject" for _, _, _, et, _ in entities):
                rejected = True
                break
            masked, part_hits = mask_text(v, ctx)
            new_h[f] = masked
            hit_list.extend(part_hits)
        if rejected:
            detail.append({"index": idx, "title": h.get("document_title") or h.get("title") or "",
                           "hits": [ {"rule": "拒绝返回", "entity_type": "reject", "count": 1}],
                           "rejected": True})
            rh = RuleHit(rule="拒绝返回(片段整条丢弃)", entity_type="reject", count=1)
            merged[("拒绝返回", "reject")] = rh
            continue
        if hit_list:
            for p in hit_list:
                key = (p.rule, p.entity_type)
                if key not in merged:
                    merged[key] = RuleHit(rule=p.rule, entity_type=p.entity_type)
                merged[key].count += p.count
        detail.append({"index": idx, "title": h.get("document_title") or h.get("title") or "",
                       "hits": [vars(p) | {} for p in hit_list], "rejected": False})
        kept.append(new_h)
    # 标题字段统一走文本脱敏（文档名也可能含敏感词；确定性令牌保证引用匹配不破）
    return kept, detail, list(merged.values())


def mask_title(value: str, ctx: MaskContext) -> str:
    if not value or not ctx:
        return value
    masked, _ = mask_text(value, ctx)
    return masked


class DeltaMasker:
    """流式输出的增量脱敏：保留尾部缓冲以处理跨 delta 的实体（如长邮箱/词典长词）。"""

    MIN_HOLD = 64

    def __init__(self, ctx: MaskContext):
        self.ctx = ctx
        self.buf = ""
        self.hold = self.MIN_HOLD
        if ctx.dict_words:
            self.hold = max(self.hold, max(len(w) for w in ctx.dict_words) + 2)
        self.hits: list[RuleHit] = []
        self._merged: dict[tuple[str, str], RuleHit] = {}

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self.buf += text
        if len(self.buf) <= self.hold:
            return ""
        emit, self.buf = self.buf[: -self.hold], self.buf[-self.hold:]
        return self._mask(emit)

    def flush(self) -> str:
        out = self._mask(self.buf)
        self.buf = ""
        return out

    def reset(self) -> None:
        self.buf = ""

    def summary(self) -> list[RuleHit]:
        return list(self._merged.values())

    def masked_count(self) -> int:
        return sum(h.count for h in self._merged.values())

    def _mask(self, text: str) -> str:
        masked, part = mask_text(text, self.ctx)
        for p in part:
            key = (p.rule, p.entity_type)
            if key not in self._merged:
                self._merged[key] = RuleHit(rule=p.rule, entity_type=p.entity_type)
            self._merged[key].count += p.count
        return masked


# ---------------------------------------------------------------------------
# 审计日志（自身脱敏：query 先过引擎，日志只记规则标签与数量）
# ---------------------------------------------------------------------------

def log_masking_async(
    *,
    user_id=None,
    username: str = "",
    scene: str,
    node: str,
    query: str,
    policy_ids: list[int],
    rule_hits,
    masked_count: int,
    blocked: bool = False,
    exempted: bool = False,
) -> None:
    """fire-and-forget 写审计日志（独立 session，异常不影响主流程）。"""
    hits = [{"rule": h.rule, "entity_type": h.entity_type, "count": h.count} for h in rule_hits]

    async def _run():
        try:
            async with SessionLocal() as s:
                s.add(MaskingLog(
                    user_id=user_id, username=username, scene=scene, node=node,
                    query=(query or "")[:500], policy_ids=policy_ids[:20], rule_hits=hits,
                    masked_count=masked_count, blocked=blocked, exempted=exempted,
                ))
                await s.commit()
        except Exception:
            pass
    try:
        asyncio.get_running_loop()
        asyncio.create_task(_run())
    except RuntimeError:
        pass
