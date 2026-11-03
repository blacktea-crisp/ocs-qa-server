"""适配层路由：/search（GET/POST）与 /health。这是 OCS 脚本唯一对接入口。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from app import pipeline
from app.adapter.schemas import SearchResponse
from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "service": "ocs-qa-server", "version": "1.0.0"}


@router.get("/search", response_model=SearchResponse)
def search_get(
    title: str = Query("", description="题目标题"),
    type: str | None = Query("unknown", description="题型 single/multiple/judgement/completion"),
    options: str | None = Query(None, description="选项，多行文本"),
    answer_trust: str | None = Query(None, description="trusted_only/prefer_trusted/allow_candidate"),
):
    r = pipeline.handle_search(title=title, qtype=type, options=options, answer_trust=answer_trust)
    return _to_response(r)


@router.post("/search", response_model=SearchResponse)
def search_post(body: dict = Body(default={})):
    r = pipeline.handle_search(
        title=body.get("title", ""),
        qtype=body.get("type"),
        options=body.get("options"),
        images=body.get("images"),
        answer_trust=body.get("answer_trust"),
    )
    return _to_response(r)


def _to_response(r) -> SearchResponse:
    return SearchResponse(
        code=r.code,
        question=r.question,
        answer=r.answer,
        answer_status=r.answer_status,
        source=r.source,
        msg=r.msg,
        request_id=getattr(r, "request_id", None),
    )
