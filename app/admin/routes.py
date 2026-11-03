"""管理 API /api/admin/*。供独立 Web 管理台调用；与 /search 解耦，不影响答题。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Header, HTTPException, Query

from app import logging_store
from app.config import get_settings
from app.store import repository as repo
from app.store.models import AnswerSource, AnswerStatus

router = APIRouter(prefix="/api/admin")


def require_admin(x_admin_token: str | None = Header(default=None)):
    token = get_settings().admin_token
    if token and x_admin_token != token:
        raise HTTPException(status_code=401, detail="X-Admin-Token 无效")


@router.get("/dashboard")
def dashboard(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    stats = logging_store.dashboard_stats()
    stats["questions_total"] = repo.count_questions()
    return stats


# ---------- 题库 ----------

@router.get("/questions")
def list_questions(
    limit: int = Query(50, le=500),
    offset: int = 0,
    q: str | None = None,
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    rows = repo.list_questions(limit=limit, offset=offset, q=q)
    # 附带每个 qkey 的答案摘要
    for r in rows:
        answers = repo.list_answers(r["qkey"])
        r["answers"] = [
            {"id": a.id, "answer": a.answer, "status": a.status.value, "source": a.source.value,
             "confidence": a.confidence, "hit_count": a.hit_count}
            for a in answers
        ]
        r["options"] = json.loads(r["options_json"])
    return {"items": rows, "total": repo.count_questions()}


@router.delete("/questions/{qkey}")
def delete_question(qkey: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    repo.delete_question(qkey)
    return {"ok": True}


# ---------- 答案候选/转正 ----------

@router.get("/answers")
def get_answers(qkey: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    answers = repo.list_answers(qkey)
    return {
        "items": [
            {"id": a.id, "answer": a.answer, "status": a.status.value, "source": a.source.value,
             "confidence": a.confidence, "hit_count": a.hit_count, "candidates": a.candidates}
            for a in answers
        ]
    }


@router.post("/answers/{answer_id}/promote")
def promote(answer_id: int, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    repo.promote_answer(answer_id)
    return {"ok": True, "status": "trusted"}


@router.post("/answers/{answer_id}/demote")
def demote(answer_id: int, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    repo.demote_answer(answer_id)
    return {"ok": True, "status": "candidate"}


@router.post("/answers/{qkey}/candidate")
def add_candidate(
    qkey: str,
    body: dict = Body(...),
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    ans = body.get("answer", "")
    confidence = float(body.get("confidence", 1.0))
    make_trusted = bool(body.get("make_trusted", False))
    if make_trusted:
        aid = repo.upsert_answer(qkey, ans, AnswerSource.MERGED, AnswerStatus.TRUSTED, confidence)
        repo.promote_answer(aid)
    else:
        aid = repo.upsert_answer(qkey, ans, AnswerSource.MERGED, AnswerStatus.CANDIDATE, confidence)
    return {"ok": True, "answer_id": aid}


# ---------- 日志 ----------

@router.get("/logs")
def list_logs(limit: int = Query(50, le=500), offset: int = 0, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    return {"items": logging_store.list_logs(limit=limit, offset=offset)}


@router.get("/logs/{request_id}")
def get_log(request_id: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    log = logging_store.get_log(request_id)
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    log["steps"] = logging_store.get_steps(request_id)
    return log


# ---------- 设置 ----------

@router.get("/settings")
def get_settings_api(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    from app.config import effective_llm

    s = get_settings()
    stored = repo.all_settings()
    llm = effective_llm()
    return {
        "effective": {
            "default_answer_trust": stored.get("default_answer_trust", s.default_answer_trust),
            "enable_llm": stored.get("enable_llm", str(s.enable_llm)),
            "enable_vision": stored.get("enable_vision", str(s.enable_vision)),
            "store_every_request": stored.get("store_every_request", str(s.store_every_request)),
            "llm_model": llm["model"],
            "vision_model": llm["vision_model"],
            "llm_base_url": llm["base_url"],
            "llm_provider": llm["provider"],
            # 安全：不回显 api_key 明文，只告知是否已设置
            "llm_api_key_set": bool(llm["api_key"]),
        },
        "stored": {k: v for k, v in stored.items() if k != "llm_api_key"},
    }


@router.put("/settings")
def update_settings(body: dict = Body(...), x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    allowed = {
        "default_answer_trust", "enable_llm", "enable_vision", "store_every_request",
        "llm_model", "vision_model", "llm_base_url", "llm_api_key",
    }
    saved = {}
    for k, v in body.items():
        if k in allowed and v is not None:
            repo.set_setting(k, str(v))
            saved[k] = str(v)
    return {"ok": True, "saved": saved}


# ---------- 服务信息（供 supervisor 状态查询的补充）----------

@router.get("/service/status")
def service_status(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    import importlib.util
    import sys

    return {
        "backend": "running",
        "python": sys.version.split()[0],
        "ok_packages": bool(importlib.util.find_spec("fastapi")),
    }
