from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, users, internal, knowledge_base, directory, document, search, settings_route, knowledge_center, dify_route, operate, governance, agent_route, agent_internal, chat_session_route, qa_route, sync_route, process_route, knowledge_gaps


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时从数据库 settings 表加载配置到运行时环境，重启/刷新后始终以 DB 为准。"""
    import os
    from sqlalchemy import select
    from kb_common.database import SessionLocal
    from kb_common.models import Setting

    # DB 设置键 → 环境变量名
    env_map = {
        "llm_base_url": "LLM_BASE_URL",
        "llm_api_key": "LLM_API_KEY",
        "llm_model": "LLM_MODEL",
        "mineru_api_key": "MINERU_API_KEY",
        "dify_base_url": "DIFY_BASE_URL",
        "dify_api_key": "DIFY_API_KEY",
        "dingtalk_app_key": "DINGTALK_APP_KEY",
        "dingtalk_app_secret": "DINGTALK_APP_SECRET",
        "dingtalk_operator_union_id": "DINGTALK_OPERATOR_UNION_ID",
    }
    try:
        async with SessionLocal() as s:
            rows = (await s.execute(select(Setting))).scalars().all()
        for row in rows:
            if row.value:
                env_key = env_map.get(row.key)
                if env_key:
                    os.environ[env_key] = str(row.value)
    except Exception:
        pass  # 表不存在/数据库未就绪时静默降级到 .env 默认值

    # 运营看板：每日 0 点定时统计（缺今日数据则启动即补统计）
    from app.routes import operate
    operate.start_operate_scheduler()

    # 钉钉知识库 → Dify 定时增量同步调度器（按各同步源 cron 字段注册任务）
    try:
        from app.services.sync.scheduler import start_sync_scheduler
        start_sync_scheduler()
    except Exception as e:
        # 同步调度器启动失败不应影响主服务（如依赖缺失/表未建）
        import logging
        logging.getLogger(__name__).warning("同步调度器启动失败: %s", e)

    try:
        yield
    finally:
        # 关闭应用（含开发热重载）时停止后台线程，避免遗留调度任务。
        try:
            from app.services.sync.scheduler import shutdown_sync_scheduler
            shutdown_sync_scheduler()
        except Exception:
            pass


app = FastAPI(title="KB API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(internal.router)
app.include_router(knowledge_base.router)
app.include_router(directory.router)
app.include_router(document.router)
app.include_router(search.router)
app.include_router(settings_route.router)
app.include_router(knowledge_center.router)
app.include_router(dify_route.router)
app.include_router(operate.router)
app.include_router(governance.router)
app.include_router(knowledge_gaps.router)
app.include_router(agent_route.router)
app.include_router(agent_internal.router)
app.include_router(chat_session_route.router)
app.include_router(qa_route.router)
app.include_router(sync_route.router)
app.include_router(process_route.router)

@app.get("/health")
def health(): return {"status": "ok"}
