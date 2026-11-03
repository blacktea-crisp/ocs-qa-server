"""候选->转正、冲突标记。"""
from __future__ import annotations

from app.store import repository as repo
from app.store.models import AnswerSource, AnswerStatus


def test_promote_answer(client, mock_llm):
    title = "转正题"
    client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
    qkey = repo.compute_qkey(title, ["A", "B"], "single")
    answers = repo.list_answers(qkey)
    assert answers[0].status.value == "candidate"
    aid = answers[0].id
    # 通过管理 API 转正
    r = client.post(f"/api/admin/answers/{aid}/promote")
    assert r.json()["status"] == "trusted"
    assert repo.get_answer(aid).status.value == "trusted"


def test_demote_answer(client, mock_llm):
    title = "降级题"
    client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
    qkey = repo.compute_qkey(title, ["A", "B"], "single")
    aid = repo.list_answers(qkey)[0].id
    client.post(f"/api/admin/answers/{aid}/promote")
    client.post(f"/api/admin/answers/{aid}/demote")
    assert repo.get_answer(aid).status.value == "candidate"


def test_conflict_marking():
    qkey = repo.compute_qkey("冲突题", ["A", "B"], "single")
    repo.upsert_question(qkey, "冲突题", repo.normalize("冲突题"), "single", ["A", "B"])
    repo.upsert_answer(qkey, "A", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
    # 另一条不同的 trusted -> 应标 conflict
    repo.upsert_answer(qkey, "B", AnswerSource.LLM, AnswerStatus.TRUSTED, 0.6)
    statuses = [a.status.value for a in repo.list_answers(qkey)]
    assert "conflict" in statuses
