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

    # LLM（默认 GLM；DeepSeek 同协议）
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""
    llm_model: str = "glm-4-flash"

    # 服务间
    kb_api_internal_url: str = "http://127.0.0.1:8000"

@lru_cache
def get_settings() -> Settings:
    return Settings()
