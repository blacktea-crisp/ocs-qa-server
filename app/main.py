"""FastAPI 应用装配。启动时初始化数据库。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapter.routes import router as search_router
from app.admin.routes import router as admin_router
from app.config import get_settings
from app.store.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OCS 自建题库后端",
        version="0.2.0",
        description="OCS 脚本题库适配 + 大模型答题 + 全链路记录 + 管理 API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(search_router)
    app.include_router(admin_router)
    return app


app = create_app()
