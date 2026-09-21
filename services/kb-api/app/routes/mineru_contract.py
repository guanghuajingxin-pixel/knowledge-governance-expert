"""MinerU 解析引擎统一契约（Pydantic schema）。

定义 /api/v1/mineru/* 显式路由的请求/响应模型，供 FastAPI 自动生成 OpenAPI 文档。
契约对本地 mineru-kit 与云端 SaaS 双引擎归一：
  - 档位统一语义三级 speed / balanced / quality（raw_tier 保留引擎原值便于排查）；
  - 产物统一 markdown + structured_json（本地 middle.json 与云端 content_list.json
    在语义上都归 structured_json，区别记入 capabilities 而非暴露给调用方）；
  - 引擎能力差异（可否取消、页码范围、大小上限）进 /v1/health 的 capabilities，
    调用方按能力适配，而非按引擎适配。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SemanticTier = Literal["speed", "balanced", "quality"]
RawTier = str

SEMANTIC_TIERS: list[dict] = [
    {"id": "speed", "local": "flash", "cloud": "pipeline",
     "description": "速度优先：最快出结果，适合预览与批量草稿"},
    {"id": "balanced", "local": "standard", "cloud": "pipeline",
     "description": "均衡：质量与速度折中，推荐默认档位"},
    {"id": "quality", "local": "advanced", "cloud": "vlm",
     "description": "效果最佳：解析最准确，速度较慢"},
]


class FeaturesOut(BaseModel):
    output_formats: list[str] = []


class CapabilitiesOut(BaseModel):
    engine: Literal["local", "cloud"]
    engine_label: str
    tiers: list[str] = ["speed", "balanced", "quality"]
    output_formats: list[str] = ["markdown", "structured_json"]
    cancelable: bool = True
    page_range: bool = True
    max_file_mb: int = 200


class HealthOut(BaseModel):
    version: str
    features: FeaturesOut = FeaturesOut()
    capabilities: CapabilitiesOut


class TierOut(BaseModel):
    id: SemanticTier
    description: str = ""
    # 请求时刻所选引擎下的原始档位值（local: flash/standard/advanced；cloud: pipeline/vlm）
    raw_tier: str | None = None
    current_model: str | None = None


class TiersOut(BaseModel):
    data: list[TierOut]


class UploadCreateIn(BaseModel):
    filename: str
    bytes: int = 0
    mime_type: str = "application/octet-stream"


class UploadOut(BaseModel):
    id: str


class OkOut(BaseModel):
    ok: bool = True


class FileOut(BaseModel):
    id: str
    filename: str


class UploadCompleteOut(BaseModel):
    id: str
    file: FileOut


class JobSourceIn(BaseModel):
    type: str = "file_id"
    file_id: str


class JobFileIn(BaseModel):
    source: JobSourceIn
    page_range: str | None = None


class JobCreateIn(BaseModel):
    files: list[JobFileIn]
    ocr_mode: Literal["auto", "txt", "ocr"] = "auto"
    output_formats: list[str] = ["markdown", "structured_json"]
    tier: str = "balanced"


class FileRefOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    file_id: str
    bytes: int | None = None
    name: str | None = None


class OutputFilesOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    markdown: FileRefOut | None = None
    structured_json: FileRefOut | None = None


class JobFileOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    output_files: OutputFilesOut | None = None


class JobProgressOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    completed: int = 0
    failed: int = 0
    total: int = 0


class JobOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    status: str
    created_at: str | None = None
    tier: str | None = None
    raw_tier: str | None = None
    progress: JobProgressOut | None = None
    files: list[JobFileOut] = []


class JobListItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    status: str
    created_at: str | None = None
    file_count: int | None = None


class JobListOut(BaseModel):
    data: list[JobListItem]


def resolve_tier(tier: str, engine: Literal["local", "cloud"]) -> tuple[str, str]:
    """语义档位/原始档位 → (semantic, raw)。未知值回退 balanced。"""
    raw_by_engine = "local" if engine == "local" else "cloud"
    for t in SEMANTIC_TIERS:
        if t["id"] == tier or t[raw_by_engine] == tier:
            return t["id"], t[raw_by_engine]
    return "balanced", SEMANTIC_TIERS[1][raw_by_engine]
