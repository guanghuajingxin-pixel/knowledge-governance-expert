"""应用配置：从环境变量 / .env 加载"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # 钉钉
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""
    dingtalk_operator_id: str = ""

    # Dify
    dify_base_url: str = "http://10.10.166.81/v1"
    dify_dataset_api_key: str = ""
    dify_default_permission: str = "all_team_members"

    # dws CLI
    dws_bin: str = "dws"
    dws_config_dir: str = str(BASE_DIR / ".dws")

    # 服务
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    admin_username: str = "admin"
    admin_password: str = "admin123"
    secret_key: str = "change_me"

    # 告警
    dingtalk_webhook: str = ""
    alert_failure_threshold: int = 1
    default_delete_policy: str = "keep"  # keep | sync

    # 数据库
    db_path: str = str(BASE_DIR / "data" / "sync.db")

    # 同步参数
    max_depth: int = 10
    max_results_per_page: int = 50
    export_format: str = "markdown"  # docx | markdown | pdf
    local_storage_dir: str = str(BASE_DIR / "data" / "downloads")
    dify_wait_indexing: bool = False
    skip_extensions: str = ".jpg,.jpeg,.png,.gif,.mp4,.mp3,.zip,.rar,.7z"

    @property
    def skip_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.skip_extensions.split(",") if e.strip()]


settings = Settings()