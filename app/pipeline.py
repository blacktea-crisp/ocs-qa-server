"""核心编排：查题库 → (识图) → 大模型 → 解析 → 入库 → 两层记录 → 返回 OCS 契约结果。"""
from __future__ import annotations

import time
import uuid

from app.config import get_settings
from app.llm import answerer, vision
from app.logging_store import log_request, log_step
from app.store import repository as repo
from app.store.models import (
    AnswerSource,
    AnswerStatus,
    SearchResult,
    TrustMode,
)

VALID_TYPES = {"single", "multiple", "judgement", "completion", "unknown"}


def _norm_type(qtype: str | None) -> str:
    t = (qtype or "unknown").strip().lower()
    return t if t in VALID_TYPES else "unknown"


def _norm_options(options) -> list[str]:
    if options is None:
        return []
    if isinstance(options, str):
        return [o for o in options.split("\n") if o.strip()]
    if isinstance(options, (list, tuple)):
        return [str(o) for o in options if str(o).strip()]
    return []


def _resolve_trust_mode(req_trust: str | None) -> str:
    allowed = {m.value for m in TrustMode}
    if req_trust and req_trust in allowed:
        return req_trust
    # 全局 Web 设置优先于 config 默认
    from app.store.repository import get_setting

    stored = get_setting("default_answer_trust")
    if stored and stored in allowed:
        return stored
    return get_settings().default_answer_trust


class _Recorder:
    """按 seq 递增记录每一步。"""

    def __init__(self, request_id: str):
        self.request_id = request_id
        self._seq = 0

    def step(self, stage, input_data=None, output_data=None, latency_ms=0, ok=True, error=None):
        self._seq += 1
        log_step(self.request_id, self._seq, stage, input_data, output_data, latency_ms, ok, error)


def handle_search(
    *,
    title: str,
    qtype: str | None,
    options,
    images: list[str] | None = None,
    answer_trust: str | None = None,
) -> SearchResult:
    settings = get_settings()
    request_id = uuid.uuid4().hex
    t0 = time.perf_counter()
    rec = _Recorder(request_id)

    title = title or ""
    qtype = _norm_type(qtype)
    opts = _norm_options(options)
    trust_mode = _resolve_trust_mode(answer_trust)
    images = images or []

    rec.step(
        "receive",
        input_data={"title": title, "type": qtype, "options": opts, "images": images, "answer_trust": trust_mode},
        output_data={"request_id": request_id},
    )

    qkey = repo.compute_qkey(title, opts, qtype)
    rec.step("normalize", input_data={"title": title, "options": opts, "type": qtype}, output_data={"qkey": qkey})

    llm_provider = settings.llm_provider
    llm_model = settings.llm_model
    prompt_tokens = completion_tokens = 0
    final_answer = None
    answer_status = None
    store_hit = False
    store_answer_id = None
    error_msg = None

    try:
        # ---- 1. 题库查询（精确 qkey）----
        st = time.perf_counter()
        existing_q = repo.get_question(qkey)
        chosen = repo.resolve_for_trust(qkey, trust_mode) if existing_q else None
        sim = None
        if chosen is None:
            # 相似检索（选项集合须吻合；防串答案）
            sim = repo.find_similar(title, opts, qtype, settings.similarity_threshold)
            if sim is not None:
                sim_qkey = sim["qkey"]
                chosen = repo.resolve_for_trust(sim_qkey, trust_mode)
                if chosen:
                    qkey = sim_qkey
        rec.step(
            "store_lookup",
            input_data={"qkey": qkey, "trust_mode": trust_mode},
            output_data={
                "exact_question": bool(existing_q),
                "similar": bool(sim),
                "hit": chosen is not None,
                "answer_id": chosen.id if chosen else None,
                "status": chosen.status.value if chosen else None,
            },
            latency_ms=int((time.perf_counter() - st) * 1000),
        )

        if chosen is not None:
            store_hit = True
            store_answer_id = chosen.id
            final_answer = chosen.answer
            answer_status = chosen.status.value
            repo.increment_hit(chosen.id)
            # 仍确保题目存在（可能在相似命中）
            if not existing_q:
                repo.upsert_question(qkey, title, repo.normalize(title), qtype, opts)
                rec.step("store_write", input_data={"qkey": qkey}, output_data={"backfilled_question": True})
        else:
            # ---- 2. 识图（仅含图时）----
            vision_text = ""
            if settings.enable_vision and (images or vision.extract_image_urls(title, opts)):
                vst = time.perf_counter()
                try:
                    vision_text, vusage, urls = vision.recognize(title, opts, images)
                    prompt_tokens += vusage.get("prompt_tokens", 0)
                    completion_tokens += vusage.get("completion_tokens", 0)
                    rec.step(
                        "vision",
                        input_data={"title": title, "options": opts, "images": images or urls},
                        output_data={"text": vision_text, "urls": urls},
                        latency_ms=int((time.perf_counter() - vst) * 1000),
                        ok=True,
                    )
                except Exception as ve:
                    rec.step(
                        "vision",
                        input_data={"title": title},
                        output_data={},
                        latency_ms=int((time.perf_counter() - vst) * 1000),
                        ok=False,
                        error=str(ve),
                    )
            else:
                rec.step("vision", output_data={"skipped": "no images"})

            effective_title = title
            if vision_text:
                effective_title = f"{title}\n[图片识别内容]\n{vision_text}"

            # ---- 3. 大模型答题 ----
            if settings.enable_llm:
                lst = time.perf_counter()
                prompt = answerer.build_prompt(effective_title, qtype, opts)
                rec.step(
                    "llm_request",
                    input_data={"provider": llm_provider, "model": llm_model, "prompt": prompt},
                    output_data={},
                )
                try:
                    ans, usage = answerer.answer(effective_title, qtype, opts)
                    prompt_tokens += usage.get("prompt_tokens", 0)
                    completion_tokens += usage.get("completion_tokens", 0)
                    rec.step(
                        "llm_response",
                        output_data={"answer": ans, "raw": usage.get("_raw"), "usage": {
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                        }},
                        latency_ms=int((time.perf_counter() - lst) * 1000),
                    )
                    # ---- 4. 解析校验 ----
                    valid = bool(ans) and ans.strip() != ""
                    rec.step(
                        "parse",
                        input_data={"raw_answer": usage.get("_raw")},
                        output_data={"answer": ans, "valid": valid},
                        ok=valid,
                        error=None if valid else "空答案",
                    )
                    if valid:
                        final_answer = ans
                        answer_status = AnswerStatus.CANDIDATE.value
                        # ---- 5. 入库（每题都入库；LLM 答案作为候选）----
                        repo.upsert_question(qkey, title, repo.normalize(title), qtype, opts)
                        aid = repo.upsert_answer(qkey, ans, AnswerSource.LLM, AnswerStatus.CANDIDATE, confidence=0.5)
                        store_answer_id = aid
                        rec.step(
                            "store_write",
                            input_data={"qkey": qkey, "answer": ans},
                            output_data={"answer_id": aid, "status": "candidate"},
                        )
                    else:
                        error_msg = "大模型未给出有效答案"
                except Exception as le:
                    error_msg = f"大模型调用失败: {le}"
                    rec.step("llm_response", output_data={}, ok=False, error=str(le),
                             latency_ms=int((time.perf_counter() - lst) * 1000))
            else:
                error_msg = "大模型已禁用且题库未命中"

    except Exception as e:  # 兜底：不向 OCS 抛 500
        error_msg = f"处理异常: {e}"
        rec.step("finalize", output_data={}, ok=False, error=str(e))

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if final_answer:
        result = SearchResult(
            code=1, question=title, answer=final_answer, answer_status=answer_status,
            source=AnswerSource.STORE.value if store_hit else AnswerSource.LLM.value,
        )
    else:
        result = SearchResult(code=0, msg=error_msg or "未找到答案")

    rec.step(
        "finalize",
        output_data={"code": result.code, "answer": result.answer, "status": result.answer_status, "msg": result.msg},
        latency_ms=latency_ms,
    )

    log_request(
        request_id,
        title=title,
        type=qtype,
        options="\n".join(opts),
        images_count=len(images) or len(vision.extract_image_urls(title, opts)),
        store_hit=store_hit,
        store_answer_id=store_answer_id,
        trust_mode=trust_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
        final_answer=final_answer,
        answer_status=answer_status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=error_msg,
    )
    # 把 request_id 附到结果上供调试
    result_req = result
    setattr(result_req, "request_id", request_id)
    return result_req
