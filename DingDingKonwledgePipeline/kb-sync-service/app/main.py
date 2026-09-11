"""FastAPI 应用入口"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .api.routes import router
from .config import BASE_DIR, settings
from .database import Base, engine
from .services.scheduler import shutdown_scheduler, start_scheduler


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(logs_dir / "app.log", rotation="10 MB", retention=14, level="INFO",
               encoding="utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.local_storage_dir).mkdir(parents=True, exist_ok=True)

    from . import models  # noqa: F401  确保模型注册
    Base.metadata.create_all(bind=engine)

    try:
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"调度器启动失败（可忽略，定时任务不可用）: {exc}")

    logger.info(f"钉钉知识库同步服务已启动: http://{settings.app_host}:{settings.app_port}")
    yield
    shutdown_scheduler()


app = FastAPI(title="钉钉知识库 → Dify 定时增量同步服务", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"service": "钉钉知识库同步服务", "status": "running", "docs": "/docs"}


static_dir = BASE_DIR / "static"
if (static_dir / "index.html").exists():
    app.mount("/admin", StaticFiles(directory=static_dir, html=True), name="admin")
