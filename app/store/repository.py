"""题库仓储：qkey 计算、归一化、题目/答案 CRUD、检索、答案候选管理。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from app.store.db import get_conn
from app.store.models import Answer, AnswerSource, AnswerStatus

# ---------- 归一化 ----------

_PUNCT = re.compile(r"[\s\u3000,，.。．、;；:：!！?？\"'“”‘’()（）\[\]【】<>《》#\-—_/\\|]+")


def normalize(text: str) -> str:
    """去标点/空格/全半角差异（简化版，与 ocsjs removeRedundant 思路一致）。"""
    if text is None:
        return ""
    # 全角转半角
    chars = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            code = 32
        elif 0xFF01 <= code <= 0xFF5E:
            code -= 0xFEE0
        chars.append(chr(code))
    s = "".join(chars).lower()
    s = _PUNCT.sub("", s)
    return s


def compute_qkey(question: str, options: list[str], qtype: str) -> str:
    """qkey = hash(归一化题干 + 归一化选项排序 + 题型)。选项不同 -> 不同 qkey。"""
    norm_q = normalize(question)
    norm_opts = sorted(normalize(o or "") for o in (options or []))
    payload = "\n".join([norm_q, "|".join(norm_opts), (qtype or "").strip().lower()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 题目 ----------

def upsert_question(qkey: str, question_raw: str, question_norm: str, qtype: str, options: list[str]) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO questions(qkey, question_raw, question_norm, type, options_json, created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(qkey) DO UPDATE SET
             question_raw=excluded.question_raw,
             question_norm=excluded.question_norm,
             type=excluded.type,
             options_json=excluded.options_json""",
        (qkey, question_raw, question_norm, qtype, json.dumps(options, ensure_ascii=False), _now()),
    )
    conn.commit()


def get_question(qkey: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM questions WHERE qkey=?", (qkey,)).fetchone()
    return dict(row) if row else None


def list_questions(limit: int = 100, offset: int = 0, q: str | None = None) -> list[dict]:
    conn = get_conn()
    if q:
        rows = conn.execute(
            "SELECT * FROM questions WHERE question_raw LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{q}%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM questions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]


def count_questions() -> int:
    return get_conn().execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]


def delete_question(qkey: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM answers WHERE qkey=?", (qkey,))
    conn.execute("DELETE FROM questions WHERE qkey=?", (qkey,))
    conn.commit()


# ---------- 答案 ----------

def _row_to_answer(row) -> Answer:
    d = dict(row)
    cands = json.loads(d.get("candidates_json") or "[]")
    return Answer(
        id=d["id"], qkey=d["qkey"], answer=d["answer"],
        source=AnswerSource(d["source"]), status=AnswerStatus(d["status"]),
        confidence=d["confidence"], hit_count=d["hit_count"],
        verified_at=d["verified_at"], created_at=d["created_at"], candidates=cands,
    )


def list_answers(qkey: str) -> list[Answer]:
    rows = get_conn().execute("SELECT * FROM answers WHERE qkey=? ORDER BY confidence DESC", (qkey,)).fetchall()
    return [_row_to_answer(r) for r in rows]


def upsert_answer(
    qkey: str,
    answer: str,
    source: AnswerSource,
    status: AnswerStatus,
    confidence: float = 0.0,
) -> int:
    """写入答案。同 qkey + 同 answer 文本则更新；否则新增。
    与已有 trusted 冲突时把新答案标记为 conflict（并存不覆盖）。"""
    conn = get_conn()
    existing = list_answers(qkey)
    # 已有相同 answer 文本
    same = next((a for a in existing if a.answer.strip() == (answer or "").strip()), None)
    if same:
        conn.execute(
            "UPDATE answers SET confidence=?, source=?, status=? WHERE id=?",
            (max(confidence, same.confidence), source.value, status.value, same.id),
        )
        conn.commit()
        return same.id

    # 冲突检测：已有 trusted 且文本不同
    trusted_diff = [a for a in existing if a.status == AnswerStatus.TRUSTED and a.answer.strip() != (answer or "").strip()]
    if trusted_diff and status == AnswerStatus.TRUSTED:
        status = AnswerStatus.CONFLICT

    cur = conn.execute(
        """INSERT INTO answers(qkey, answer, source, status, confidence, hit_count, verified_at, candidates_json, created_at)
           VALUES(?,?,?,?,?,0,NULL,'[]',?)""",
        (qkey, answer, source.value, status.value, confidence, _now()),
    )
    conn.commit()
    return cur.lastrowid


def add_candidate(qkey: str, answer: str, source: AnswerSource, confidence: float = 0.0) -> None:
    """把一条答案作为候选追加到已有 answers 行（或新建 candidate 行），用于审计多候选。"""
    existing = list_answers(qkey)
    cand = {"answer": answer, "source": source.value, "confidence": confidence, "ts": _now()}
    if existing:
        primary = existing[0]
        cands = primary.candidates
        if not any(c.get("answer", "").strip() == (answer or "").strip() for c in cands):
            cands.append(cand)
            conn = get_conn()
            conn.execute("UPDATE answers SET candidates_json=? WHERE id=?", (json.dumps(cands, ensure_ascii=False), primary.id))
            conn.commit()
    # 若没有主行，由 upsert_answer 负责建行；此处不重复。


def get_answer(answer_id: int) -> Answer | None:
    row = get_conn().execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
    return _row_to_answer(row) if row else None


def promote_answer(answer_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE answers SET status='trusted', verified_at=? WHERE id=?", (_now(), answer_id))
    conn.commit()


def demote_answer(answer_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE answers SET status='candidate', verified_at=NULL WHERE id=?", (answer_id,))
    conn.commit()


def increment_hit(answer_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE answers SET hit_count=hit_count+1 WHERE id=?", (answer_id,))
    conn.commit()


def resolve_for_trust(qkey: str, trust_mode: str) -> Answer | None:
    """按信任策略从题库为 qkey 选答案。"""
    answers = list_answers(qkey)
    if not answers:
        return None
    trusted = [a for a in answers if a.status == AnswerStatus.TRUSTED]
    if trust_mode == "trusted_only":
        return _best(trusted)
    if trust_mode == "prefer_trusted":
        return _best(trusted) or _best([a for a in answers if a.status == AnswerStatus.CANDIDATE])
    if trust_mode == "allow_candidate":
        return _best(trusted) or _best([a for a in answers if a.status in (AnswerStatus.CANDIDATE, AnswerStatus.CONFLICT)])
    return _best(trusted)


def _best(items: list[Answer]) -> Answer | None:
    if not items:
        return None
    return sorted(items, key=lambda a: (a.confidence, a.hit_count), reverse=True)[0]


# ---------- 相似检索（防串答案：必须选项集合吻合）----------

def find_similar(question: str, options: list[str], qtype: str, threshold: float) -> dict | None:
    """返回匹配的 question 行（含其答案）。相似阶段强制校验选项集合吻合，否则不命中。"""
    from difflib import SequenceMatcher

    qn = normalize(question)
    opt_set = sorted(normalize(o or "") for o in (options or []))
    if not qn:
        return None
    conn = get_conn()
    rows = conn.execute("SELECT * FROM questions").fetchall()
    best = None
    best_score = 0.0
    for r in rows:
        r_opts = sorted(normalize(o or "") for o in json.loads(r["options_json"]))
        # 选项集合不吻合直接跳过（防同题干不同选项串答案）
        if r_opts != opt_set:
            continue
        if (r["type"] or "").strip().lower() != (qtype or "").strip().lower():
            continue
        score = SequenceMatcher(None, qn, r["question_norm"]).ratio()
        if score > best_score:
            best_score = score
            best = dict(r)
    if best and best_score >= threshold:
        best["_score"] = best_score
        return best
    return None


# ---------- settings_kv ----------

def get_setting(key: str, default: str | None = None) -> str | None:
    row = get_conn().execute("SELECT value FROM settings_kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings_kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def all_settings() -> dict:
    rows = get_conn().execute("SELECT key,value FROM settings_kv").fetchall()
    return {r["key"]: r["value"] for r in rows}
