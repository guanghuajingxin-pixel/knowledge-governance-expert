from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录（config.py 在 services/kb-common/kb_common/config.py，上三级为仓库根）下的 .env
# 无论从哪个服务目录运行都能找到
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # 基础设施
    database_url: str = "postgresql+asyncpg://dev:dev123456@127.0.0.1:5432/dev_db"
    redis_url: str = "redis://:dev123456@127.0.0.1:6379/0"
    es_host: str = "http://127.0.0.1:9200"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    kkfv_url: str = "http://127.0.0.1:8012"

    # 认证
    jwt_secret: str = "change-me-in-prod"
    jwt_algo: str = "HS256"
    jwt_ttl_minutes: int = 1440

    # 模型
    bge_embed_model: str = "BAAI/bge-m3"
    bge_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    embed_dim: int = 1024
    mineru_api_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""          # 运行时可被 settings 表覆盖
    # 本地 MinerU 解析引擎（mineru-api 常驻服务，见 services/mineru）；
    # 置空字符串可禁用本地引擎、强制走云 API。
    mineru_local_url: str = "http://127.0.0.1:2028"

    # LLM（默认 GLM；DeepSeek 同协议）
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""
    llm_model: str = "glm-4-flash"

    # Dify 知识库（用于智能问答 Agent；Service API 端点需含端口与 /v1）
    dify_base_url: str = "http://127.0.0.1:8088/v1"
    dify_api_key: str = ""           # Dataset API Key 或 App API Key
    dify_dataset_ids: str = ""       # 默认检索的数据集 ID，逗号分隔
    dify_retrieval_top_k: int = 50
    dify_score_threshold: float = 0.4
    # 检索方式：semantic_search / full_text_search / hybrid_search
    dify_search_method: str = "semantic_search"
    # Dify 侧重排（需在 Dify 控制台配置 Rerank 模型；未配置时应置 false，否则检索 400）
    dify_reranking_enable: bool = False

    # 服务间
    kb_api_internal_url: str = "http://127.0.0.1:8000"

    # 钉钉（企业知识库数据来源）
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""
    dingtalk_operator_union_id: str = ""   # 调用知识库 API 的操作人 unionId

@lru_cache
def get_settings() -> Settings:
    return Settings()
