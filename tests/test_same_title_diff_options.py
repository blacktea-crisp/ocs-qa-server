"""重点：同题干、不同选项 -> 两条独立记录、各自独立答案。"""
from __future__ import annotations

from app.store import repository as repo
from app.store.models import AnswerSource, AnswerStatus


def test_same_title_diff_options_independent(client, mock_llm, monkeypatch):
    title = "以下哪个是正确的？"

    # 第一组选项，模库答案 A
    def fake1(t, qtype, options):
        return options[0], {"prompt_tokens": 1, "completion_tokens": 1, "model": "mock", "_raw": options[0]}

    from app.llm import answerer as ansmod

    monkeypatch.setattr(ansmod, "answer", fake1)
    r1 = client.post("/search", json={"title": title, "type": "single", "options": ["选项甲", "选项乙"]})
    assert r1.json()["answer"] == "选项甲"

    # 第二组不同选项，模库答案 B（不同）
    def fake2(t, qtype, options):
        return options[1], {"prompt_tokens": 1, "completion_tokens": 1, "model": "mock", "_raw": options[1]}

    monkeypatch.setattr(ansmod, "answer", fake2)
    r2 = client.post("/search", json={"title": title, "type": "single", "options": ["苹果", "香蕉"]})
    assert r2.json()["answer"] == "香蕉"

    # 两个 qkey 不同
    k1 = repo.compute_qkey(title, ["选项甲", "选项乙"], "single")
    k2 = repo.compute_qkey(title, ["苹果", "香蕉"], "single")
    assert k1 != k2
    assert repo.get_question(k1) is not None
    assert repo.get_question(k2) is not None
    # 各自答案独立
    assert repo.resolve_for_trust(k1, "prefer_trusted").answer == "选项甲"
    assert repo.resolve_for_trust(k2, "prefer_trusted").answer == "香蕉"


def test_qkey_differs_by_option_order_insensitive():
    # 选项顺序不同但集合相同 -> 同 qkey（选项排序归一）
    k1 = repo.compute_qkey("题目", ["A选项", "B选项"], "single")
    k2 = repo.compute_qkey("题目", ["B选项", "A选项"], "single")
    assert k1 == k2
