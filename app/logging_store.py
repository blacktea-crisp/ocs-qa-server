"""两层记录：request_logs（请求级概要）+ request_steps（步骤级明细）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.store.db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_step(
    request_id: str,
    seq: int,
    stage: str,
    input_data=None,
    output_data=None,
    latency_ms: int = 0,
    ok: bool = True,
    error: str | None = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO request_steps(request_id, seq, stage, input_json, output_json, latency_ms, ok, error, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            request_id,
            seq,
            stage,
            json.dumps(input_data, ensure_ascii=False) if input_data is not None else None,
            json.dumps(output_data, ensure_ascii=False) if output_data is not None else None,
            latency_ms,
            1 if ok else 0,
            error,
            _now(),
        ),
    )
    conn.commit()


def log_request(
    request_id: str,
    *,
    title: str,
    type: str,
    options: str,
    images_count: int = 0,
    store_hit: bool = False,
    store_answer_id: int | None = None,
    trust_mode: str = "",
    llm_provider: str = "",
    llm_model: str = "",
    final_answer: str | None = None,
    answer_status: str | None = None,
    latency_ms: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_estimate: float = 0.0,
    error: str | None = None,
) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO request_logs(
             request_id, title, type, options, images_count, store_hit, store_answer_id,
             trust_mode, llm_provider, llm_model, final_answer, answer_status,
             latency_ms, prompt_tokens, completion_tokens, cost_estimate, error, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(request_id) DO UPDATE SET
             final_answer=excluded.final_answer, answer_status=excluded.answer_status,
             latency_ms=excluded.latency_ms, error=excluded.error""",
        (
            request_id,
            title,
            type,
            options,
            images_count,
            1 if store_hit else 0,
            store_answer_id,
            trust_mode,
            llm_provider,
            llm_model,
            final_answer,
            answer_status,
            latency_ms,
            prompt_tokens,
            completion_tokens,
            cost_estimate,
            error,
            _now(),
        ),
    )
    conn.commit()


def get_log(request_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM request_logs WHERE request_id=?", (request_id,)).fetchone()
    return dict(row) if row else None


def get_steps(request_id: str) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM request_steps WHERE request_id=? ORDER BY seq ASC", (request_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def list_logs(limit: int = 100, offset: int = 0, only_errors: bool = False,
              store_hit: bool | None = None, q: str | None = None) -> list[dict]:
    sql = "SELECT * FROM request_logs WHERE 1=1"
    params: list = []
    if only_errors:
        sql += " AND error IS NOT NULL AND error!=''"
    if store_hit is not None:
        sql += " AND store_hit=?"
        params.append(1 if store_hit else 0)
    if q:
        sql += " AND title LIKE ?"
        params.append(f"%{q}%")
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = get_conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM request_logs").fetchone()["c"]
    hits = conn.execute("SELECT COUNT(*) c FROM request_logs WHERE store_hit=1").fetchone()["c"]
    errs = conn.execute("SELECT COUNT(*) c FROM request_logs WHERE error IS NOT NULL AND error!=''").fetchone()["c"]
    tokens = conn.execute(
        "SELECT COALESCE(SUM(prompt_tokens+completion_tokens),0) t, COALESCE(SUM(cost_estimate),0) c FROM request_logs"
    ).fetchone()
    avg_lat = conn.execute("SELECT COALESCE(AVG(latency_ms),0) a FROM request_logs").fetchone()["a"]
    # 最近 20 条用于趋势
    recent = conn.execute(
        "SELECT request_id, store_hit, latency_ms, created_at FROM request_logs ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    return {
        "total_requests": total,
        "store_hits": hits,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "errors": errs,
        "total_tokens": tokens["t"],
        "total_cost": round(tokens["c"], 6),
        "avg_latency_ms": round(avg_lat, 1),
        "recent": [dict(r) for r in recent],
    }
