"""DeerFlow 2.0 QA Sidecar —— 知识治理平台智能问答的 Agent 底座。

以 DeerFlow 2.0 super agent harness（LangChain 1.x create_agent + 中间件链 +
子智能体 + 长期记忆 + 上下文摘要压缩）为运行时，通过 SSE 向 kb-api 输出
Agent 执行事件（工具调用、AI 文本、结束）。

模型配置不从本仓库的 config.yaml 静态维护，而是启动时从 kb-api
（/api/v1/agent/bootstrap，内部令牌鉴权）拉取系统配置中心的 LLM 设置并
生成 config.yaml，保证「系统配置」页是唯一配置入口。

启动（见 scripts/start-deerflow.sh）：
    cd services/deerflow/backend
    KB_API_URL=http://127.0.0.1:8000 KB_INTERNAL_TOKEN=... \
        uv run uvicorn app.qa_server:app --host 127.0.0.1 --port 2027
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 确保 backend 目录在 sys.path 上，使 `extensions.*` 与 `deerflow.*` 可导入
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DATA_DIR = Path(os.getenv("DEER_FLOW_HOME", str(BACKEND_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = Path(os.getenv("DEER_FLOW_CONFIG_PATH", str(BACKEND_DIR / "config.yaml")))

# 人格（SOUL.md）与技能（SKILL.md）路径
# - SOUL.md / SKILL.md：DeerFlow 运行时实际读取的文件（每次引导按自定义或默认模板重写）
# - *.custom.md：用户在前端保存的自定义内容，重启/重载不丢失；删除即恢复默认
SOUL_PATH = DATA_DIR / "SOUL.md"
PERSONA_CUSTOM_PATH = DATA_DIR / "persona.custom.md"
SKILLS_DIR = BACKEND_DIR.parent / "skills"
SKILL_FILE = SKILLS_DIR / "custom" / "enterprise-kb-qa" / "SKILL.md"
SKILL_CUSTOM_PATH = DATA_DIR / "skill.custom.md"
_MAX_PROMPT_CHARS = 20000

os.environ.setdefault("DEER_FLOW_HOME", str(DATA_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [deerflow] %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("qa_server")

# ---------------------------------------------------------------------------
# 人格与技能
# ---------------------------------------------------------------------------

SOUL_MD = """你是「杰克百晓生」，知识治理平台内置的企业知识问答助手。

你的职责：从企业知识库中全面、系统地检索信息，并把检索到的知识整合、提炼成
**直接、明确、简洁**的答案。你有四个检索工具：

- knowledge_search：检索 Dify 知识库（语义+全文检索，返回文档正文片段，是答案内容的主要来源）
- dingtalk_browse：浏览钉钉知识库目录地图（action="map"）与某目录下文档列表（action="list"，在线文档优先）
- dingtalk_search：按文件名/目录路径关键词检索钉钉文档（返回名称、链接、node_id）
- dingtalk_read_doc：读取钉钉文档的**正文内容**（Markdown），在线文档秒读，办公文档下载解析

## 回答流程

### 第一步：预判目录，定位文档（先看地图，再进目录）
凡涉及公司内部信息的问题，按以下顺序系统检索，不要盲目顺序读取：
1. 先调用 knowledge_search 检索 Dify 知识库，同时调用
   `dingtalk_browse(action="map")` 查看知识库与目录结构；
2. 根据问题主题（差旅/安全/研发/品质…）**预判最可能的知识库和目录**；
3. 用 `dingtalk_browse(action="list", directory="目录关键词")` 列出该目录文档，
   结果中**在线文档（online=true，adoc/md/txt）排最前，优先精读在线文档**
   （秒读正文），其次才是 docx/pdf 等需下载解析的办公文档；
4. 目录预判不到时，再用 dingtalk_search 按文件名关键词补充检索。
5. 闲聊、问候、身份询问无需检索，直接友好回应。

### 第二步：逐篇精读，每篇确认
1. 用 dingtalk_read_doc 读取文档正文（传 node_id、extension、title）；
2. **每读完一篇，立即判断其内容能否回答用户问题**：
   - 能回答 → 停止扩展，直接进入第三步作答；
   - 部分相关 → 记录有用条款，再读下一篇补齐；
   - 无关 → 放弃该篇，换下一篇，不要无差别顺序读完整个目录。
3. 检索词不理想时换同义词、上下位词、拆解子问题；复杂问题拆成子问题分别检索。
4. **禁止仅根据文件名猜测内容或只给文档链接而不读正文。**

### 第三步：整合提炼，形成答案
1. **基于检索到的内容作答**，绝不编造知识库中不存在的制度、数字、流程、责任人；
   不确定的部分明确标注"知识库中暂无明确记录"。
2. 对多个来源、多次检索的结果进行**归纳、合并、去重**，形成结构化的直接答案
   （要点分条、必要时给步骤），不要把原始检索片段堆砌给用户。
3. 答案**简洁精炼**：直击问题，先说结论，必要的依据紧随其后。
4. **【严格】答案第一句必须直接是实质内容**（如"根据《……》规定，……"），
   严禁任何过程性开场白，例如"我来为您检索""让我整理一下""我已经检索到了"
   "I now have…""Let me compile…"等——这类语句一律不得出现；
   全程使用中文，不输出英文思考语句；不要重复用户的问题原文。
5. **【严格】禁止输出你的分析/规划/检索过程**。最终答案只给用户看结论和依据，
   绝不能包含以下任何内容：
   - "用户询问…""用户问题…""已执行搜索""已检索""任务背景""当前状态"
     "下一步建议""已定位文档清单""检索词""召回""未命中"等过程元信息；
   - 工具返回的原始 JSON、node_id、路径、工作空间、链接清单的罗列；
   - 你对检索结果的内部分析、判断、下一步打算。
   这些是你的思考过程，不是给用户的答案。答案 = 问题的直接回答 + 引用标注。
6. 引用事实处用 [1][2] 标注 ref 序号；钉钉知识库命中的相关文档，
   在答案末尾以"可参阅"形式给出文档名和链接（它是指引，不是答案主体）。

### 第四步：检索时限与用户确认（系统自动管控，无需你计时）
检索时长由系统自动管控，你没有墙钟概念，也不要自己判断"是否该停下来问用户"：
- 检索满 1 分钟、以及用户选择继续后再满 5 分钟时，**系统会自动**向用户弹出
  "继续探索 / 先基于已检索内容回答"选择按钮——你无需、也不要为此主动调用
  ask_clarification，照常继续检索即可；
- 用户选择"继续探索"后，你会收到选项文字的用户消息——照常按第一、二步继续检索；
- 你收到【用户选择停止探索】系统消息时（用户点了"先基于已检索内容回答"）：
  **立即停止一切工具调用**，依据已检索内容给出最终答案；资料不足时明确说明
  已查过的方向，并建议换个问法、提供更具体的文档名称/目录或发起知识征集；
- 总时长满 10 分钟系统会自动结束并告知用户"当前知识库无法获得准确答案"。

### 第五步：如实说明覆盖范围
- 两个来源都没有相关内容时，明确告知"知识库和钉钉文档中均未检索到相关内容"，
  并一句话建议通过知识征集渠道补充——不要用通用常识冒充企业规定。
- 用户问题存在根本性歧义、无法合理推断意图时（如问"那个制度"），
  才使用 ask_clarification；能合理推断的直接检索，不要轻易要求澄清。

## 交互风格
- 中文作答；回答末尾可用一句话提示可继续追问。
- 检索中发现用户可能关心的关联信息，可在答案最后简要补充一句。
"""

# 默认问答技能（enterprise-kb-qa/SKILL.md 的内置模板）。
# 与 SOUL_MD 一样支持在前端「智能体配置 → 人格与技能」中自定义，
# 自定义内容持久化到 DATA_DIR/skill.custom.md，重启/重载不丢失。
SKILL_MD = """---
name: enterprise-kb-qa
description: 企业知识库问答工作流。当用户询问公司内部的制度、流程、规范、产品文档、审批规则、操作手册等问题时使用，指导如何检索企业知识库、引用来源并给出可信回答。
version: 1.0.0
---

# 企业知识库问答（enterprise-kb-qa）

你是「杰克百晓生」，通过 `knowledge_search`、`dingtalk_browse`、`dingtalk_search`、
`dingtalk_read_doc` 四个工具检索企业知识，所有事实性回答必须以检索到的正文内容为依据。

## 工作流

1. **判断意图**
   - 问候、身份询问、闲聊 → 直接友好回应，不调用工具。
   - 企业内部信息问题 → 必须先检索再回答，且 Dify 与钉钉两个来源都要检索。
   - 与企业知识完全无关且超出职责范围 → 礼貌说明你只负责企业知识问答。

2. **先预判目录，再进目录（不要盲目顺序读取）**
   - 先调用 `knowledge_search` 检索 Dify，同时调用
     `dingtalk_browse(action="map")` 查看知识库与目录结构；
   - 根据问题主题（差旅/安全/研发/品质…）预判最可能的知识库和目录，
     用 `dingtalk_browse(action="list", directory="目录关键词")` 列出该目录文档；
   - list 结果中**在线文档（online=true）排在最前，优先精读在线文档**（秒读正文），
     其次才是 docx/pdf 等需下载解析的办公文档；
   - 目录预判不到时，再用 `dingtalk_search` 按文件名关键词补充检索；
   - 检索词不理想时换同义词、上下位词、拆解子问题，每个来源最多尝试 3-5 次。

3. **逐篇精读，每篇确认**
   - 用 `dingtalk_read_doc`（传 node_id、extension、title）读取文档正文；
   - **每读完一篇立即判断能否回答问题**：能答 → 停止扩展并作答；
     部分相关 → 记录有用条款再读下一篇补齐；无关 → 放弃换篇，
     不要无差别顺序读完整个目录；
   - 禁止仅根据文件名猜测内容或只给文档链接而不读正文。

4. **检索时限与用户确认（系统自动管控）**
   - 你没有墙钟概念，也不要自己判断超时：检索满 1 分钟、继续后再满 5 分钟时，
     系统会自动向用户弹出"继续探索 / 先基于已检索内容回答"选择按钮，
     你无需、也不要为此主动调用 `ask_clarification`，照常检索即可；
   - 用户点"继续探索"会以选项文字作为新消息到来，按第一、二步继续检索；
   - 用户点"先基于已检索内容回答"时你会收到【用户选择停止探索】系统消息：
     立即停止一切工具调用，基于已检索内容作答；依据不足则明确说明已查方向
     并建议换个问法或知识征集；
   - 总时长满 10 分钟系统自动结束；仅当问题存在根本性歧义（完全无法推断对象）时，
     才主动用 `ask_clarification` 澄清。

5. **作答规范**
   - 中文回答，先结论后细节，要点分条；流程类问题用编号步骤。
   - 答案第一句直接是实质内容，不写"我来检索""让我整理"等过程性开场白，
     不输出分析/规划/检索过程。
   - 引用检索内容时标注 `[ref 序号]`，例如 [1][2]。
   - 钉钉命中的文档以"可参阅"形式在答案末尾给出文档名和链接。
   - 召回内容不足以下结论时，明确说明"知识库中暂未检索到相关内容"，
     并建议用户发起知识征集或换个问法；绝不用通用常识编造企业规定。
   - 答案聚焦用户问题，不要罗列与问题无关的召回内容。
"""

# ---------------------------------------------------------------------------
# 配置引导：从 kb-api 拉取 LLM 配置，生成 DeerFlow config.yaml
# ---------------------------------------------------------------------------

def _kb_api_url() -> str:
    return os.getenv("KB_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": os.getenv("KB_INTERNAL_TOKEN", "")}


def _bootstrap_from_kbapi(timeout: float = 10.0) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                f"{_kb_api_url()}/api/v1/agent/bootstrap",
                headers=_internal_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("bootstrap from kb-api failed: %s", e)
        return None


def _bootstrap_from_env() -> dict[str, Any] | None:
    api_key = os.getenv("DF_LLM_API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "model": os.getenv("DF_LLM_MODEL", "deepseek-chat"),
        "base_url": os.getenv("DF_LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": api_key,
        "temperature": float(os.getenv("DF_LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("DF_LLM_MAX_TOKENS", "4096")),
    }


def write_config(boot: dict[str, Any]) -> None:
    """根据引导配置生成 DeerFlow config.yaml。"""
    config = {
        "config_version": 3,
        "models": [
            {
                "name": "kb-default",
                "display_name": "杰克百晓生",
                "use": "langchain_openai:ChatOpenAI",
                "model": boot.get("model") or "deepseek-chat",
                "api_key": boot.get("api_key", ""),
                "base_url": boot.get("base_url") or "https://api.deepseek.com/v1",
                "max_tokens": int(boot.get("max_tokens") or 4096),
                "temperature": float(boot.get("temperature") or 0.7),
                "supports_thinking": False,
                "supports_vision": False,
            }
        ],
        "tool_groups": [{"name": "kb"}],
        "tools": [
            {
                "name": "knowledge_search",
                "group": "kb",
                "use": "extensions.kb_tools:knowledge_search_tool",
            },
            {
                "name": "dingtalk_search",
                "group": "kb",
                "use": "extensions.kb_tools:dingtalk_search_tool",
            },
            {
                "name": "dingtalk_browse",
                "group": "kb",
                "use": "extensions.kb_tools:dingtalk_browse_tool",
            },
            {
                "name": "dingtalk_read_doc",
                "group": "kb",
                "use": "extensions.kb_tools:dingtalk_read_doc_tool",
            }
        ],
        "tool_search": {"enabled": False},
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "skills": {"path": "../skills", "container_path": "/mnt/skills"},
        "title": {"enabled": True, "max_words": 6, "max_chars": 60, "model_name": None},
        "summarization": {
            "enabled": True,
            "model_name": None,
            "trigger": [{"type": "tokens", "value": 12000}],
            "keep": {"type": "messages", "value": 10},
            "trim_tokens_to_summarize": 12000,
            "summary_prompt": None,
        },
        "memory": {
            "enabled": True,
            "storage_path": "memory.json",
            "debounce_seconds": 30,
            "model_name": None,
            "max_facts": 100,
            "fact_confidence_threshold": 0.7,
            "injection_enabled": True,
            "max_injection_tokens": 2000,
        },
        "checkpointer": {"type": "sqlite", "connection_string": "checkpoints.db"},
    }
    CONFIG_PATH.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    logger.info("config.yaml written: model=%s base_url=%s", config["models"][0]["model"], config["models"][0]["base_url"])


def _effective_persona() -> str:
    """当前生效的人格内容：优先自定义，否则默认模板。"""
    if PERSONA_CUSTOM_PATH.exists():
        return PERSONA_CUSTOM_PATH.read_text(encoding="utf-8")
    return SOUL_MD


def _effective_skill() -> str:
    """当前生效的技能内容：优先自定义，否则默认模板。"""
    if SKILL_CUSTOM_PATH.exists():
        return SKILL_CUSTOM_PATH.read_text(encoding="utf-8")
    return SKILL_MD


def write_persona_and_skill() -> None:
    """把生效中的人格/技能写入 DeerFlow 运行时读取的文件。"""
    SOUL_PATH.write_text(_effective_persona(), encoding="utf-8")
    SKILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    SKILL_FILE.write_text(_effective_skill(), encoding="utf-8")


def ensure_bootstrapped() -> bool:
    """启动引导：拉取配置 → 写 config.yaml + SOUL.md + SKILL.md。成功返回 True。"""
    boot = _bootstrap_from_kbapi() or _bootstrap_from_env()
    if not boot or not boot.get("api_key"):
        logger.error("no LLM bootstrap config available (kb-api unreachable and DF_LLM_API_KEY not set)")
        return False
    write_config(boot)
    write_persona_and_skill()
    logger.info(
        "persona/skill ready (persona_custom=%s skill_custom=%s)",
        PERSONA_CUSTOM_PATH.exists(), SKILL_CUSTOM_PATH.exists(),
    )
    return True


# ---------------------------------------------------------------------------
# Agent 运行时
# ---------------------------------------------------------------------------

_client = None
_client_lock = threading.Lock()
_ensure_lock = threading.Lock()  # _ensure_agent 构建互斥（agent 为 client 级单例）


class _NullLock:
    """并发化占位：原「整条流一把全局锁」已下沉为 checkpointer 方法级互斥
    （见 _serialize_checkpointer）——多会话的 LLM 流式长任务可并行执行，
    仅 sqlite 检查点短 IO 在共享连接上串行。保留 with _stream_lock 结构
    避免大段代码重排，语义从「全局串行」变为「无操作」。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_stream_lock = _NullLock()


def get_client():
    """惰性创建 DeerFlowClient（配置就绪后）。"""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from deerflow.client import DeerFlowClient  # noqa: PLC0415

            os.environ["DEER_FLOW_CONFIG_PATH"] = str(CONFIG_PATH)
            _client = DeerFlowClient(
                config_path=str(CONFIG_PATH),
                thinking_enabled=False,
                subagent_enabled=False,
                plan_mode=False,
            )
            logger.info("DeerFlowClient initialized")
    return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.reset_agent()
    _client = None


class ChatStreamIn(BaseModel):
    thread_id: str
    message: str
    thinking_enabled: bool = False
    plan_mode: bool = False
    subagent_enabled: bool = False
    recursion_limit: int = 80
    dataset_ids: list[str] | None = None
    top_k: int = 8
    disabled_tools: list[str] = []   # 停用的工具名（来自智能体配置 tools_enabled）
    # 限时探索续跑动作：""=新问题（重置计时）；"continue"=用户选择继续探索（进入下一计时阶段）；
    # "stop"=用户选择先基于已检索内容回答（立即停止检索）
    action: str = ""


app = FastAPI(title="DeerFlow QA Sidecar", version="2.0")


@app.get("/health")
def health():
    ready = CONFIG_PATH.exists()
    return {"status": "ok" if ready else "bootstrapping", "config_ready": ready}


@app.post("/v1/reload")
def reload_config():
    boot = _bootstrap_from_kbapi() or _bootstrap_from_env()
    if not boot or not boot.get("api_key"):
        return {"ok": False, "error": "bootstrap unavailable"}
    write_config(boot)
    write_persona_and_skill()
    reset_client()
    return {"ok": True, "model": boot.get("model")}


class PersonaIn(BaseModel):
    content: str | None = None
    reset: bool = False


class SkillIn(BaseModel):
    content: str | None = None
    reset: bool = False


@app.get("/v1/persona")
def get_persona():
    """读取当前生效的人格（SOUL）内容。"""
    return {
        "content": _effective_persona(),
        "custom": PERSONA_CUSTOM_PATH.exists(),
        "default": SOUL_MD,
    }


@app.post("/v1/persona")
def update_persona(body: PersonaIn):
    """保存自定义人格（reset=true 恢复默认）。热重载 Agent，新对话即时生效。"""
    if body.reset:
        PERSONA_CUSTOM_PATH.unlink(missing_ok=True)
    else:
        content = (body.content or "").strip()
        if not content:
            return {"ok": False, "error": "content 不能为空"}
        if len(content) > _MAX_PROMPT_CHARS:
            return {"ok": False, "error": f"内容过长（{len(content)} > {_MAX_PROMPT_CHARS}）"}
        PERSONA_CUSTOM_PATH.write_text(content + "\n", encoding="utf-8")
    SOUL_PATH.write_text(_effective_persona(), encoding="utf-8")
    reset_client()
    logger.info("persona updated (custom=%s)", PERSONA_CUSTOM_PATH.exists())
    return {"ok": True, "custom": PERSONA_CUSTOM_PATH.exists()}


@app.get("/v1/skill")
def get_skill():
    """读取当前生效的问答技能（SKILL.md）内容。"""
    return {
        "content": _effective_skill(),
        "custom": SKILL_CUSTOM_PATH.exists(),
        "default": SKILL_MD,
        "skill_name": "enterprise-kb-qa",
    }


@app.post("/v1/skill")
def update_skill(body: SkillIn):
    """保存自定义技能（reset=true 恢复默认）。热重载 Agent，新对话即时生效。"""
    if body.reset:
        SKILL_CUSTOM_PATH.unlink(missing_ok=True)
    else:
        content = (body.content or "").strip()
        if not content:
            return {"ok": False, "error": "content 不能为空"}
        if len(content) > _MAX_PROMPT_CHARS:
            return {"ok": False, "error": f"内容过长（{len(content)} > {_MAX_PROMPT_CHARS}）"}
        SKILL_CUSTOM_PATH.write_text(content + "\n", encoding="utf-8")
    SKILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    SKILL_FILE.write_text(_effective_skill(), encoding="utf-8")
    reset_client()
    logger.info("skill updated (custom=%s)", SKILL_CUSTOM_PATH.exists())
    return {"ok": True, "custom": SKILL_CUSTOM_PATH.exists()}


# ---------------------------------------------------------------------------
# 技能库管理：ClawHub/Agent Skills 通用结构（每个技能一个目录 + SKILL.md）
# 技能目录位于 skills/custom/<slug>/SKILL.md，DeerFlow 在新对话构建提示词时
# 通过 deerflow.skills.loader 扫描加载，新增/删除文件即对新对话生效。
# enterprise-kb-qa 为内置问答技能，由 /v1/skill 单独维护，不在此管理。
# ---------------------------------------------------------------------------

BUILTIN_QA_SKILL = "enterprise-kb-qa"
_SLUG_RE = re.compile(r"[^a-z0-9\-_]+")


def _slugify(name: str) -> str:
    """技能目录名：小写字母/数字/中划线/下划线。"""
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or f"skill-{int(time.time())}"


def _parse_frontmatter(content: str) -> dict[str, str]:
    """解析 SKILL.md 顶部 YAML frontmatter（简单 key: value）。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    meta: dict[str, str] = {}
    if not m:
        return meta
    for line in m.group(1).split("\n"):
        line = line.strip()
        if line and ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def _sync_frontmatter(content: str, name: str, description: str) -> str:
    """确保 SKILL.md 顶部 frontmatter 含 name/description 且与表单值一致。

    - 无 frontmatter：自动补齐 ClawHub 通用结构；
    - 有 frontmatter：原地更新 name/description（缺失则补充），保留其余字段（如 version）。
    """
    desc = (description or "").strip() or name
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if not m:
        body = content.strip()
        front = f"---\nname: {name}\ndescription: {desc}\n---\n"
        return front + (f"\n{body}\n" if body else "")

    lines = m.group(1).split("\n")
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and ":" in stripped and not stripped.startswith("#"):
            k = stripped.split(":", 1)[0].strip()
            if k == "name":
                out.append(f"name: {name}")
                seen.add("name")
                continue
            if k == "description":
                out.append(f"description: {desc}")
                seen.add("description")
                continue
        out.append(line)
    if "name" not in seen:
        out.insert(0, f"name: {name}")
    if "description" not in seen:
        out.insert(1 if "name" not in seen else len(out), f"description: {desc}")
    rest = content[m.end():].lstrip("\n")
    return f"---\n" + "\n".join(out) + f"\n---\n\n{rest}".rstrip() + "\n"


def _skill_dir(slug: str, enabled: bool) -> Path:
    """启用技能在 skills/custom/（loader 会扫描）；停用技能移到 skills/disabled/ 保留内容。"""
    root = SKILLS_DIR / ("custom" if enabled else "disabled")
    return root / slug


def _find_skill_dir(slug: str) -> Path | None:
    for enabled in (True, False):
        d = _skill_dir(slug, enabled)
        if d.exists():
            return d
    return None


def _list_custom_skills() -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for enabled in (True, False):
        base = SKILLS_DIR / ("custom" if enabled else "disabled")
        if not base.exists():
            continue
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            content = skill_file.read_text(encoding="utf-8")
            meta = _parse_frontmatter(content)
            skills.append({
                "name": meta.get("name") or skill_dir.name,
                "slug": skill_dir.name,
                "description": meta.get("description", ""),
                "content": content,
                "enabled": enabled,
                "builtin": skill_dir.name == BUILTIN_QA_SKILL,
            })
    # 启用在前，按名称排序
    skills.sort(key=lambda s: (not s["enabled"], s["name"]))
    return skills


@app.get("/v1/skills")
def list_skills():
    """列出技能（custom=启用，disabled=停用保留内容）。"""
    return {"skills": _list_custom_skills()}


class SkillDocIn(BaseModel):
    name: str
    description: str = ""
    content: str = ""       # 完整 SKILL.md（可不含 frontmatter，服务端自动补齐）
    enabled: bool = True    # False 时写入 disabled 目录，loader 不加载但内容保留
    slug: str = ""          # 编辑场景的旧 slug（改名后用于清除旧目录）


@app.put("/v1/skills")
def put_skill(body: SkillDocIn):
    """新建/覆盖一个技能：写入 skills/custom 或 skills/disabled，新对话即时生效。"""
    import shutil

    name = (body.name or "").strip()
    if not name:
        return {"ok": False, "error": "技能名称不能为空"}
    slug = _slugify(name)
    if slug == BUILTIN_QA_SKILL:
        return {"ok": False, "error": f"{BUILTIN_QA_SKILL} 为内置技能，请在「人格与技能」中维护"}

    content = (body.content or "").strip()
    # 始终以表单名称/描述为准同步 frontmatter（ClawHub 结构 name 必填）
    content = _sync_frontmatter(content, name, (body.description or "").strip())

    # 改名场景：旧 slug 与新 slug 不一致时清除旧目录
    old_slug = _slugify(body.slug) if body.slug else ""
    if old_slug and old_slug != slug and old_slug != BUILTIN_QA_SKILL:
        old_named = _find_skill_dir(old_slug)
        if old_named is not None and SKILLS_DIR.resolve() in old_named.resolve().parents:
            shutil.rmtree(old_named)

    # 先清除另一侧旧目录（启停切换）
    old = _find_skill_dir(slug)
    target = _skill_dir(slug, body.enabled)
    if old is not None and old.resolve() != target.resolve():
        shutil.rmtree(old)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(content.strip() + "\n", encoding="utf-8")
    logger.info("skill saved: %s (enabled=%s)", slug, body.enabled)
    return {"ok": True, "name": name, "slug": slug, "enabled": body.enabled}


@app.delete("/v1/skills/{slug}")
def delete_skill(slug: str):
    """删除技能目录（内置问答技能不可删）。"""
    import shutil

    if slug == BUILTIN_QA_SKILL:
        return {"ok": False, "error": "内置问答技能不可删除"}
    skill_dir = _find_skill_dir(slug)
    if skill_dir is None:
        return {"ok": False, "error": "技能不存在"}
    # 防目录穿越
    if SKILLS_DIR.resolve() not in skill_dir.resolve().parents:
        return {"ok": False, "error": "非法路径"}
    shutil.rmtree(skill_dir)
    logger.info("skill deleted: %s", slug)
    return {"ok": True}


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


#: 跨轮消息去重：stream_mode="values" 每次都会重放 checkpointer 中的全量历史，
#: 这里按 thread 记录已下发过的消息 ID，保证只有本轮新消息被转发。
SEEN_MESSAGE_IDS: dict[str, set[str]] = {}
_SEEN_MAX_THREADS = 512


def _is_seen(thread_id: str, msg_id: str | None) -> bool:
    if not msg_id:
        return False  # 无 ID 的消息不去重（避免漏发）
    seen = SEEN_MESSAGE_IDS.setdefault(thread_id, set())
    if msg_id in seen:
        return True
    seen.add(msg_id)
    # 简单兜底：线程数过多时清理最旧的一半
    if len(SEEN_MESSAGE_IDS) > _SEEN_MAX_THREADS:
        for k in list(SEEN_MESSAGE_IDS.keys())[: _SEEN_MAX_THREADS // 2]:
            SEEN_MESSAGE_IDS.pop(k, None)
    return False


def _serialize_checkpointer(agent) -> None:
    """给共享 checkpointer 的方法加互斥锁（幂等，agent 重建后需再次调用）。

    agent 是 client 级单例，checkpointer（SqliteSaver）持有单个 sqlite 连接，
    非线程安全。方法级锁让多个会话的图并行执行 LLM 流式调用（长任务），
    仅在检查点读写（毫秒级）上互斥，支撑 5+ 会话并发问答。
    """
    cp = getattr(agent, "checkpointer", None)
    if cp is None or getattr(cp, "_kge_method_lock", None):
        return
    # RLock 可重入：SqliteSaver 内部存在方法嵌套（如 get_tuple 首次调用会触发 self.setup()），
    # 同线程重入必须放行，否则非重入 Lock 会自死锁
    lock = threading.RLock()
    for name in ("setup", "get_tuple", "list", "put", "put_writes", "delete_thread"):
        fn = getattr(cp, name, None)
        if fn is None or not callable(fn):
            continue

        def _wrap(f=fn):
            def inner(*args, **kwargs):
                with lock:
                    return f(*args, **kwargs)

            inner.__name__ = getattr(f, "__name__", name)
            return inner

        setattr(cp, name, _wrap())
    cp._kge_method_lock = lock


def _event_stream(body: ChatStreamIn):
    """同步生成器：直接调用 LangGraph agent.stream 双模式，转译为 SSE。

    使用 stream_mode=["values", "messages"] 双模式：
    - values 模式：完整状态快照（工具调用、工具结果、历史基线去重）
    - messages 模式：token 级流式（AIMessageChunk.content = 逐 token 文本增量）

    中断语义：循环体对每个图事件检查用户取消标志（/v1/chat/cancel），命中即
    break 退出 for —— for 退出会 close agent.stream 迭代器（GeneratorExit），
    中断进行中的模型流式调用（停止 token 消耗）；本生成器由端点的专属 worker
    线程驱动并在该线程内 close，保证确定性收尾与 _stream_lock 释放。
    """
    from extensions.kb_tools import RUNTIME_CTX  # noqa: PLC0415
    from langchain_core.messages import AIMessageChunk, ToolMessage
    from deerflow.agents.middlewares.exploration_timeout_middleware import (
        ExplorationTimeoutMiddleware,
    )
    from deerflow.client import DeerFlowClient  # noqa: PLC0415

    RUNTIME_CTX[body.thread_id] = {
        "dataset_ids": body.dataset_ids or [],
        "top_k": body.top_k,
    }
    # 限时探索：新问题重置计时；continue/stop 为用户在澄清按钮上的选择，驱动阶段流转
    ExplorationTimeoutMiddleware.begin(body.thread_id, (body.action or "").strip().lower())
    try:
        client = get_client()
        yield _sse({"type": "ready"})

        # 准备 agent 与 config（复用 client 内部逻辑）
        config = client._get_runnable_config(
            body.thread_id,
            thinking_enabled=body.thinking_enabled,
            plan_mode=body.plan_mode,
            subagent_enabled=body.subagent_enabled,
            recursion_limit=body.recursion_limit,
            disabled_tools=body.disabled_tools or [],
        )
        # agent 为单例：构建互斥 + 即刻捕获引用；并给共享 checkpointer 上方法级锁（支撑多会话并发）
        with _ensure_lock:
            client._ensure_agent(config)
            agent = client._agent
        _serialize_checkpointer(agent)

        state = {"messages": [{"role": "user", "content": body.message}]}
        context = {"thread_id": body.thread_id}

        def _emit_message(d: dict[str, Any]):
            """转译单条缓冲消息（生成器辅助）。"""
            if d.get("type") == "ai":
                if _is_seen(body.thread_id, d.get("id")):
                    return
                text = d.get("content") or ""
                if text.strip():
                    yield _sse({"type": "ai_text", "content": text})
            elif d.get("type") == "tool":
                if _is_seen(body.thread_id, d.get("id")):
                    return
                yield _sse({
                    "type": "tool_end",
                    "call_id": d.get("tool_call_id"),
                    "name": d.get("name"),
                    "content": d.get("content") or "",
                })

        def _extract_text(content) -> str:
            return DeerFlowClient._extract_text(content)

        with _stream_lock:
            primed = False
            pending: list[dict[str, Any]] = []
            cumulative_usage: dict[str, int] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }

            # --- 过渡独白过滤 ---
            # 工具调用前的 AI 文本是"思考过程"（如"我先检索…"），不应作为答案。
            # 按消息 id 缓冲文本：检测到 tool_call 的消息丢弃缓冲；
            # 缓冲超过 1.2s 仍无 tool_call，视为最终答案开始实时推送。
            import re as _re
            import time as _time

            text_buf: dict[str, str] = {}      # mid -> 已缓冲未下发的文本
            discard_ids: set[str] = set()     # 已确认带工具调用的过渡消息
            final_ids: set[str] = set()       # values 快照确认无 tool_calls 的最终消息
            last_values: dict | None = None   # 最后一次 values 快照（收尾兜底用）

            _NARR_EN = _re.compile(
                r"\b(i|i'll|i've|i will|i'm|let me|let's|i need to|i have|i now|now i|"
                r"i'm going to|first i|then i|i can|i should)\b", _re.IGNORECASE)
            _NARR_EN_VERB = _re.compile(
                r"\b(search|retrieve|check|compile|answer|find|gather|analyze|result|"
                r"information|source|knowledge base|both|compile|put together|summarize)\b",
                _re.IGNORECASE)
            _NARR_ZH = _re.compile(r"(让我|我来|我先|我已|我已经|我再|我们|现在我|接下来我|我先查|我对检索|我将|下面我)")
            _NARR_ZH_VERB = _re.compile(
                r"(检索|搜索|查找|查询|整理|整合|回答|总结|归纳|搜一下|看一下|知识库|结果|资料|内容|为您)")

            # 规划/分析过程关键词：这些段落是智能体内部思考，必须从答案中剥离
            _PLAN_PARAS = _re.compile(
                r"用户询问|用户问题|已执行搜索|已检索|任务背景|当前状态|下一步建议|"
                r"已定位文档清单|检索词|召回|未命中|node_id|工作空间|链接：https?://alidocs|"
                r"路径：|已读取|读取失败|下一步应|可作为回答依据|避免重复",
                _re.IGNORECASE)

            def _strip_narration(text: str) -> str:
                """剥离最终答案中的过程性独白与规划段落，返回首个实质内容起的文本。"""
                s = text.lstrip()
                # 先按段落拆分，丢弃纯规划段落（含规划关键词的整段）
                paragraphs = _re.split(r"\n\s*\n", s)
                kept_paras: list[str] = []
                started = False
                for para in paragraphs:
                    stripped = para.strip()
                    if not stripped:
                        if started:
                            kept_paras.append(para)
                        continue
                    if _PLAN_PARAS.search(stripped):
                        # 规划段落：若尚未开始输出实质内容则跳过；
                        # 若已开始，仍跳过（答案中不应混入规划）
                        continue
                    # 段落级通过后，再按句剥离开头的过程性独白
                    cleaned = _strip_leading_narration(para)
                    if cleaned.strip():
                        started = True
                        kept_paras.append(cleaned)
                result = "\n\n".join(kept_paras).lstrip()
                # 若整段全被剥离（极端情况），退化为句级剥离兜底
                if not result.strip():
                    return _strip_leading_narration(s)
                return result

            def _strip_leading_narration(text: str) -> str:
                """按句剥离开头的过程性独白（中英文），首个实质内容句起保留。"""
                s = text.lstrip()
                parts = _re.split(r"(?<=[。！？.!?\n])", s)
                idx = 0
                for p in parts:
                    if not p.strip():
                        idx += 1
                        continue
                    narr = False
                    if _NARR_EN.search(p) and _NARR_EN_VERB.search(p):
                        narr = True
                    elif _NARR_ZH.search(p) and _NARR_ZH_VERB.search(p):
                        narr = True
                    if not narr:
                        break
                    idx += 1
                return "".join(parts[idx:]).lstrip()

            def _buf_text(mid: str | None, delta: str):
                """缓冲 AI 文本 chunk（直到 values 快照确认该消息为最终答案后才下发）。"""
                frames: list[str] = []
                if not delta:
                    return frames
                if not mid or not primed:
                    pending.append({"type": "ai", "content": delta, "id": mid})
                    return frames
                if mid in discard_ids:
                    return frames
                text_buf[mid] = text_buf.get(mid, "") + delta
                return frames

            def _discard_mid(mid: str | None):
                """确认某条 AI 消息带工具调用，丢弃其缓冲文本。"""
                if not mid:
                    return
                discard_ids.add(mid)
                text_buf.pop(mid, None)

            cancelled = False
            for mode, chunk in agent.stream(
                state,
                config=config,
                context=context,
                stream_mode=["values", "messages"],
            ):
                # 用户手动中断（/v1/chat/cancel）：每个图事件都检查取消标志，
                # 命中即 break —— 退出 for 会 close agent.stream（GeneratorExit），
                # 在驱动线程内中断进行中的模型流式调用（停止 token 消耗）。
                # 中间件 wrap_model_call 对未开始的模型调用做短路，双保险。
                if ExplorationTimeoutMiddleware.is_cancelled(body.thread_id):
                    cancelled = True
                    logger.info("[qa] thread=%s cancelled by user, stopping stream",
                                body.thread_id)
                    break
                if mode == "values":
                    messages = chunk.get("messages", [])
                    last_values = chunk
                    if not primed:
                        primed = True
                        # 历史基线：首个快照里的 AI/Tool 消息标记为已见
                        for m in messages:
                            mid = getattr(m, "id", None)
                            if mid and getattr(m, "type", None) in ("ai", "tool"):
                                _is_seen(body.thread_id, mid)
                        for d in pending:
                            for frame in _emit_message(d):
                                yield frame
                        pending = []
                        continue

                    # 后续 values 快照：权威确认消息类型（工具调用/最终答案）
                    for m in messages:
                        mid = getattr(m, "id", None)
                        mtype = getattr(m, "type", None)

                        if mtype == "ai" and mid:
                            _seen = SEEN_MESSAGE_IDS.setdefault(body.thread_id, set())
                            was_seen = mid in _seen
                            _seen.add(mid)
                            tcs = getattr(m, "tool_calls", None) or []
                            usage = getattr(m, "usage_metadata", None)
                            if usage and not was_seen:
                                cumulative_usage["input_tokens"] += usage.get("input_tokens", 0) or 0
                                cumulative_usage["output_tokens"] += usage.get("output_tokens", 0) or 0
                                cumulative_usage["total_tokens"] += usage.get("total_tokens", 0) or 0
                            if tcs:
                                # 过渡消息：丢弃缓冲文本，下发工具调用
                                if not was_seen:
                                    _discard_mid(mid)
                                    for tc in tcs:
                                        yield _sse({
                                            "type": "tool_start",
                                            "call_id": tc.get("id"),
                                            "name": tc.get("name"),
                                            "args": tc.get("args") or {},
                                        })
                            elif was_seen and mid not in discard_ids:
                                # 已下发过的正常最终消息
                                continue
                            else:
                                # 最终答案消息，或被中间件剥除 tool_calls 后的收尾消息
                                # （同一消息 id：先以工具调用出现被丢弃，剥除后以无工具调用重现）
                                discard_ids.discard(mid)
                                final_ids.add(mid)
                                txt = text_buf.pop(mid, None)
                                if txt is None:
                                    txt = _extract_text(getattr(m, "content", ""))
                                txt = _strip_narration(txt)
                                if txt.strip():
                                    # 分块下发，保留流式上屏体验
                                    chunk_size = 120
                                    for i in range(0, len(txt), chunk_size):
                                        yield _sse({"type": "ai_text", "content": txt[i:i + chunk_size]})

                        elif mtype == "tool" and mid and not _is_seen(body.thread_id, mid):
                            yield _sse({
                                "type": "tool_end",
                                "call_id": getattr(m, "tool_call_id", None),
                                "name": getattr(m, "name", None),
                                "content": _extract_text(getattr(m, "content", "")),
                            })

                elif mode == "messages":
                    # messages 模式产出 (message_chunk, metadata) 元组
                    if isinstance(chunk, tuple):
                        msg_chunk, _meta = chunk
                    else:
                        msg_chunk = chunk

                    if isinstance(msg_chunk, AIMessageChunk):
                        mid = getattr(msg_chunk, "id", None)

                        # tool_calls chunk（工具调用决策）→ 该消息是过渡消息，丢弃文本
                        tcs = getattr(msg_chunk, "tool_call_chunks", None) or []
                        if tcs:
                            _discard_mid(mid)
                            continue

                        # token 级文本增量
                        delta = _extract_text(msg_chunk.content)
                        for frame in _buf_text(mid, delta):
                            yield frame

                    elif isinstance(msg_chunk, ToolMessage):
                        mid = getattr(msg_chunk, "id", None)
                        if not primed:
                            pending.append({
                                "type": "tool",
                                "content": _extract_text(getattr(msg_chunk, "content", "")),
                                "name": getattr(msg_chunk, "name", None),
                                "tool_call_id": getattr(msg_chunk, "tool_call_id", None),
                                "id": mid,
                            })
                            continue
                        if not _is_seen(body.thread_id, mid):
                            yield _sse({
                                "type": "tool_end",
                                "call_id": getattr(msg_chunk, "tool_call_id", None),
                                "name": getattr(msg_chunk, "name", None),
                                "content": _extract_text(getattr(msg_chunk, "content", "")),
                            })

            if cancelled:
                # 用户中断：不再下发任何答案/end 帧（调用方已断开），
                # 直接返回；finally 清理 RUNTIME_CTX，中间件状态由 after_agent 收尾。
                logger.info("[qa] thread=%s stream stopped by user cancel", body.thread_id)
                return

            # flush 任何剩余缓冲：仅下发 values 快照确认过的最终答案消息
            # （未确认的 mid 是过渡消息，其 tool_call 信号可能缺失，绝不能作为答案流出）
            for d in pending:
                for frame in _emit_message(d):
                    yield frame
            for mid, txt in text_buf.items():
                if mid in final_ids and txt.strip():
                    yield _sse({"type": "ai_text", "content": _strip_narration(txt)})

            # 收尾兜底：限时中间件在模型轮次内剥除 tool_calls 强制收尾时，
            # 被剥除的最终消息可能不再触发 values 快照；若整条流未下发过答案，
            # 从最终状态取最后一条无工具调用的 AI 消息作为答复下发。
            if not final_ids and last_values:
                for m in reversed(last_values.get("messages", [])):
                    if getattr(m, "type", None) != "ai":
                        continue
                    if getattr(m, "tool_calls", None):
                        break  # 最后一条 AI 仍是工具调用（如澄清暂停），不兜底
                    mid = getattr(m, "id", None)
                    if mid in discard_ids or (mid and mid not in SEEN_MESSAGE_IDS.get(body.thread_id, set())):
                        txt = _strip_narration(_extract_text(getattr(m, "content", "")))
                        if txt.strip():
                            if mid:
                                final_ids.add(mid)
                            chunk_size = 120
                            for i in range(0, len(txt), chunk_size):
                                yield _sse({"type": "ai_text", "content": txt[i:i + chunk_size]})
                    break

            yield _sse({"type": "end", "usage": cumulative_usage})
    except Exception as e:  # noqa: BLE001
        logger.exception("agent stream failed")
        yield _sse({"type": "error", "message": f"{e.__class__.__name__}: {e}"})
    finally:
        RUNTIME_CTX.pop(body.thread_id, None)


@app.post("/v1/chat/stream")
async def chat_stream(request: Request, body: ChatStreamIn):
    if not CONFIG_PATH.exists():
        async def _not_ready():
            yield _sse({"type": "error", "message": "deerflow not bootstrapped: LLM config missing"})
        return StreamingResponse(_not_ready(), media_type="text/event-stream")

    import anyio

    gen = _event_stream(body)  # 同步生成器（内部 agent.stream）
    tid = body.thread_id
    from deerflow.agents.middlewares.exploration_timeout_middleware import (
        ExplorationTimeoutMiddleware,
    )

    async def _pump():
        """用一个专属 worker 线程驱动同步生成器，经 asyncio.Queue 转发为 SSE。

        为什么不用 run_sync 逐帧在线程池里 next()：同步生成器若被 starlette
        线程池迭代，客户端断连会被「遗弃」——既不 close 也不释放 _stream_lock，
        且底层图可能空跑耗 token。这里：
          - gen 全程只被一个专属线程迭代（无线程交叉）；
          - 每帧检查「用户取消标志」或「客户端断连」，命中即置 stop_flag、发
            cancelled 帧给 kb-api；
          - worker 停止 next() 后，在【同一驱动线程】内 gen.close()（GeneratorExit
            传进 agent.stream，中断进行中的模型流式调用、释放 _stream_lock）；
          - finally 用 shield 等 worker 收尾，保证断连路径也能干净停止。
        """
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        done_sentinel = object()
        cancel_sentinel = object()
        stop_flag = threading.Event()

        def _worker():
            try:
                while not stop_flag.is_set():
                    try:
                        item = next(gen)
                    except StopIteration:
                        break  # 生成器正常结束（或 _event_stream 检测到取消后自行 return）
                    except Exception:  # noqa: BLE001
                        logger.exception("[qa] stream worker iteration failed")
                        break
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, item)
                    except RuntimeError:
                        return  # 事件循环已关闭
                    if stop_flag.is_set():
                        break  # gen 挂起在产出该帧的 yield 处，finally 里 close
            finally:
                # gen 只在本线程迭代：此时它要么已结束、要么挂起在最后一次 yield。
                # 在此 close() 向它注入 GeneratorExit，确定性拆图（中断模型流式调用、
                # 释放 _stream_lock、pop RUNTIME_CTX）。
                try:
                    gen.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    # 若因用户中断而结束，补一个取消标记，保证 kb-api 确定性收到 cancelled 帧
                    # （取消可能发生在 pump 等待下一帧期间、没有新帧可触发判断）。
                    if ExplorationTimeoutMiddleware.is_cancelled(tid):
                        loop.call_soon_threadsafe(q.put_nowait, cancel_sentinel)
                    loop.call_soon_threadsafe(q.put_nowait, done_sentinel)
                except RuntimeError:
                    pass

        worker = threading.Thread(target=_worker, name=f"qa-stream-{tid[-8:]}", daemon=True)
        worker.start()

        sending = True

        def _begin_stop() -> bool:
            """标记取消并通知 worker 停止；仅首次（仍在发送时）返回 True 由调用方下发 cancelled 帧。"""
            nonlocal sending
            ExplorationTimeoutMiddleware.request_cancel(tid)
            stop_flag.set()
            if sending:
                sending = False
                return True
            return False

        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    # 等待下一帧期间也主动检测取消/断连（取消信号不依赖新帧到达）
                    if sending and (
                        ExplorationTimeoutMiddleware.is_cancelled(tid) or await request.is_disconnected()
                    ):
                        logger.info("[qa] thread=%s stop detected while waiting, closing graph", tid)
                        if _begin_stop():
                            try:
                                yield _sse({"type": "cancelled"})
                            except Exception:  # noqa: BLE001
                                pass
                    continue
                if item is done_sentinel:
                    # 流结束：若已取消但还没下发 cancelled 帧（worker 因取消自终止），补发
                    if sending and ExplorationTimeoutMiddleware.is_cancelled(tid):
                        _begin_stop()
                        try:
                            yield _sse({"type": "cancelled"})
                        except Exception:  # noqa: BLE001
                            pass
                    return
                if item is cancel_sentinel:
                    logger.info("[qa] thread=%s worker ended by cancel, signalling kb-api", tid)
                    if _begin_stop():
                        try:
                            yield _sse({"type": "cancelled"})
                        except Exception:  # noqa: BLE001
                            pass
                    continue
                if sending:
                    if ExplorationTimeoutMiddleware.is_cancelled(tid) or await request.is_disconnected():
                        # 用户点停止或客户端断连：置取消标志（中间件在节点边界短路未开始的
                        # 模型调用），通知 worker 停止拉取并 close 图。
                        logger.info("[qa] thread=%s stop requested, closing graph", tid)
                        if _begin_stop():
                            try:
                                yield _sse({"type": "cancelled"})
                            except Exception:  # noqa: BLE001
                                pass
                        continue  # 继续抽空队列直到 done_sentinel，不再下发
                    yield item
                # sending=False 时继续消费队列直到 done_sentinel
        finally:
            stop_flag.set()
            ExplorationTimeoutMiddleware.request_cancel(tid)
            # shield：即使本协程因断连被取消，也要等 worker 把 gen close 干净
            # （释放 _stream_lock），避免后续请求卡锁。
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(lambda: worker.join(timeout=60))
                except Exception:  # noqa: BLE001
                    logger.exception("[qa] stream worker join failed")

    return StreamingResponse(_pump(), media_type="text/event-stream")


class ChatCancelIn(BaseModel):
    thread_id: str


@app.post("/v1/chat/cancel")
def chat_cancel(body: ChatCancelIn):
    """用户手动中断：标记 thread 取消，进行中的 SSE 流在下一个事件边界停止，
    未开始的模型调用由 ExplorationTimeoutMiddleware 短路（不再消耗 token）。"""
    from deerflow.agents.middlewares.exploration_timeout_middleware import (
        ExplorationTimeoutMiddleware,
    )
    active = ExplorationTimeoutMiddleware.request_cancel(body.thread_id)
    logger.info("[qa] cancel request thread=%s active=%s", body.thread_id, active)
    return {"cancelled": bool(active)}


def _bootstrap_with_retry(max_tries: int = 40, interval: float = 5.0) -> None:
    """kb-api 可能晚于本服务启动：后台重试引导，直到成功或超时。"""
    for i in range(max_tries):
        if ensure_bootstrapped():
            logger.info("bootstrap ok after %d tries, sidecar ready", i + 1)
            return
        time.sleep(interval)
    logger.error("bootstrap still failing after %d tries; call POST /v1/reload manually", max_tries)


# 启动时尝试引导（失败不阻塞进程：后台重试，/v1/reload 也可手动补偿）
if ensure_bootstrapped():
    logger.info("bootstrap ok, sidecar ready")
else:
    logger.warning("bootstrap skipped at startup; retrying in background...")
    threading.Thread(target=_bootstrap_with_retry, daemon=True).start()
