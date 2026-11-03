"""大模型答题：四题型、分隔符、候选入库、信任策略。"""
from __future__ import annotations

from app.store import repository as repo


def test_multiple_join_hash(client, mock_llm):
    title = "以下哪些是编程语言？"
    r = client.post("/search", json={"title": title, "type": "multiple", "options": "Python\nJava\nHTML\nCSS"})
    data = r.json()
    assert data["code"] == 1
    assert "#" in data["answer"]  # 多选用 # 连接
    # 入库为候选
    qkey = repo.compute_qkey(title, ["Python", "Java", "HTML", "CSS"], "multiple")
    answers = repo.list_answers(qkey)
    assert answers and answers[0].status.value == "candidate"


def test_judgement_answer(client, mock_llm):
    r = client.post("/search", json={"title": "天是蓝的吗", "type": "judgement", "options": ["正确", "错误"]})
    assert r.json()["answer"] in ("正确", "错误")


def test_completion_answer(client, mock_llm):
    r = client.post("/search", json={"title": "水的化学式", "type": "completion", "options": []})
    assert r.json()["code"] == 1


def test_trusted_only_blocks_candidate(client, mock_llm):
    title = "只信可信题"
    # 第一次：LLM 生成 -> candidate
    r1 = client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"], "answer_trust": "trusted_only"})
    # 没有 trusted，且 LLM 生产的只是 candidate, trusted_only 下第二次不会再命中
    r2 = client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"], "answer_trust": "trusted_only"})
    qkey = repo.compute_qkey(title, ["A", "B"], "single")
    # candidate 存在，但 trusted_only 不会据此直接命中（应再次走 LLM）
    assert repo.resolve_for_trust(qkey, "trusted_only") is None


def test_prefer_trusted_uses_candidate_after(client, mock_llm):
    title = "优先可信题"
    client.post("/search", json={"title": title, "type": "single", "options": ["甲", "乙"], "answer_trust": "prefer_trusted"})
    qkey = repo.compute_qkey(title, ["甲", "乙"], "single")
    # prefer_trusted 下候选可用
    ans = repo.resolve_for_trust(qkey, "prefer_trusted")
    assert ans is not None and ans.status.value == "candidate"


def test_allow_candidate(client, mock_llm):
    title = "允许候选题"
    client.post("/search", json={"title": title, "type": "single", "options": ["X", "Y"], "answer_trust": "allow_candidate"})
    qkey = repo.compute_qkey(title, ["X", "Y"], "single")
    assert repo.resolve_for_trust(qkey, "allow_candidate") is not None
