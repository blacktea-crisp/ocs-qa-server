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
def list_logs(
    limit: int = Query(50, le=500),
    offset: int = 0,
    only_errors: bool = Query(False),
    store_hit: str | None = Query(None),
    q: str | None = Query(None),
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    sh = None
    if store_hit in ("1", "true"):
        sh = True
    elif store_hit in ("0", "false"):
        sh = False
    return {"items": logging_store.list_logs(limit=limit, offset=offset, only_errors=only_errors, store_hit=sh, q=q)}


@router.get("/logs/export")
def logs_export(
    format: str = Query("csv", pattern="^(csv|json)$"),
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    import csv
    import io
    from datetime import datetime

    from fastapi.responses import Response

    rows = logging_store.list_logs(limit=5000)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    header = list(rows[0].keys()) if rows else []
    if format == "json":
        import json as _json

        body = _json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(content=body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="logs_{stamp}.json"'})
    buf = io.StringIO()
    if header:
        writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return Response(content=("\ufeff" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="logs_{stamp}.csv"'})


@router.get("/logs/{request_id}")
def get_log(request_id: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    log = logging_store.get_log(request_id)
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    log["steps"] = logging_store.get_steps(request_id)
    # 命中信息：若命中题库，附带命中的答案记录
    log["hit_answer"] = None
    aid = log.get("store_answer_id")
    if aid:
        a = repo.get_answer(int(aid))
        if a:
            log["hit_answer"] = {
                "id": a.id, "answer": a.answer, "status": a.status.value,
                "source": a.source.value, "hit_count": a.hit_count, "confidence": a.confidence,
            }
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


# ---------- 提供商配置档案（llm_profiles）----------

@router.get("/llm/profiles")
def list_profiles(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    return {"items": repo.list_profiles()}


@router.post("/llm/profiles")
def create_profile(body: dict = Body(...), x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    try:
        pid = repo.create_profile(
            name,
            body.get("provider") or "custom",
            body.get("base_url") or "",
            body.get("api_key") or "",
            body.get("model") or "",
            body.get("vision_model") or "",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建失败：{e}")
    if body.get("activate"):
        repo.activate_profile(pid)
    return {"ok": True, "id": pid}


@router.put("/llm/profiles/{pid}")
def update_profile(pid: int, body: dict = Body(...), x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    if not repo.get_profile(pid):
        raise HTTPException(status_code=404, detail="档案不存在")
    repo.update_profile(pid, body)
    return {"ok": True}


@router.delete("/llm/profiles/{pid}")
def delete_profile(pid: int, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    repo.delete_profile(pid)
    return {"ok": True}


@router.post("/llm/profiles/{pid}/activate")
def activate_profile(pid: int, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    if not repo.get_profile(pid):
        raise HTTPException(status_code=404, detail="档案不存在")
    repo.activate_profile(pid)
    return {"ok": True}


# ---------- 测试连接 / 获取模型列表 ----------

@router.post("/llm/test")
def llm_test(body: dict = Body(default={}), x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    from app.llm import client as llm_client

    # 允许传入临时配置测试（不落库）；否则用当前有效配置
    cfg = None
    if body and any(k in body for k in ("base_url", "model", "api_key")):
        cur = llm_client.effective_llm()
        cfg = {
            "base_url": body.get("base_url") or cur["base_url"],
            "api_key": body.get("api_key") or cur["api_key"],
            "model": body.get("model") or cur["model"],
            "timeout": cur.get("timeout", 60),
        }
    return llm_client.test_connection(cfg)


@router.get("/llm/models")
def llm_models(
    base_url: str | None = None,
    api_key: str | None = None,
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    from app.llm import client as llm_client

    cfg = None
    if base_url or api_key:
        cur = llm_client.effective_llm()
        cfg = {"base_url": base_url or cur["base_url"], "api_key": api_key or cur["api_key"], "model": cur["model"]}
    return llm_client.list_models(cfg)


# ---------- 导出数据 ----------

@router.get("/export")
def export_data(
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
    type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    include_candidates: bool = Query(False),
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    import csv
    import io
    from datetime import datetime

    from fastapi.responses import Response

    rows = repo.export_rows(qtype=type, date_from=date_from, date_to=date_to, include_candidates=include_candidates)
    header = ["qkey", "question", "type", "options", "answer", "answer_status",
              "source", "confidence", "hit_count", "answer_json", "created_at"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format == "json":
        import json as _json

        body = _json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(content=body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="qa_export_{stamp}.json"'})

    if format == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "questions"
        ws.append(header)
        for r in rows:
            ws.append([r.get(h) for h in header])
        buf = io.BytesIO()
        wb.save(buf)
        return Response(content=buf.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="qa_export_{stamp}.xlsx"'})

    # csv（带 BOM 便于 Excel 识别中文）
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    body = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="qa_export_{stamp}.csv"'})


# ---------- 题库详情（单题完整信息）----------

@router.get("/questions/{qkey}/detail")
def question_detail(qkey: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    import json as _json

    q = repo.get_question(qkey)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    q["options"] = _json.loads(q.get("options_json") or "[]")
    q["options_structured"] = repo.get_options(qkey)
    answers = repo.list_answers(qkey)
    q["answers"] = [
        {"id": a.id, "answer": a.answer, "status": a.status.value, "source": a.source.value,
         "confidence": a.confidence, "hit_count": a.hit_count, "verified_at": a.verified_at,
         "created_at": a.created_at, "answer_json": a.answer_json, "candidates": a.candidates}
        for a in answers
    ]
    # 相关日志（按题目精确匹配）
    logs = [l for l in logging_store.list_logs(limit=200) if (l.get("title") or "").strip() == (q["question_raw"] or "").strip()]
    q["logs"] = logs[:20]
    return q


# ---------- OCS 配置生成（网页获取/显示）----------

@router.get("/ocs-config")
def ocs_config(
    version: str = Query("v2", pattern="^(v1|v2)$"),
    host: str = Query("127.0.0.1"),
    port: int = Query(0),
    trust: str = Query("prefer_trusted", pattern="^(trusted_only|prefer_trusted|allow_candidate)$"),
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token)
    import sys as _sys
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent.parent
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    from scripts.export_ocs_config import build_config

    p = port or int(__import__("app.config", fromlist=["get_settings"]).get_settings().port)
    cfg = build_config(host, p, trust, version)
    return {"ok": True, "version": version, "config": cfg,
            "text": json.dumps(cfg, ensure_ascii=False, indent=2)}
