"""适配层 /search 测试：命中/未命中/GET/POST/编码。"""
from __future__ import annotations


def _seed_one(title="1+1 等于多少？", qtype="single", options=("1", "2", "3", "4"), answer="2"):
    from app.store import repository as repo
    from app.store.models import AnswerSource, AnswerStatus

    opts = list(options)
    qkey = repo.compute_qkey(title, opts, qtype)
    repo.upsert_question(qkey, title, repo.normalize(title), qtype, opts)
    repo.upsert_answer(qkey, answer, AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
    return qkey


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search_get_hit(client, mock_llm):
    _seed_one()
    r = client.get("/search", params={"title": "1+1 等于多少？", "type": "single", "options": "1\n2\n3\n4"})
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 1
    assert data["answer"] == "2"
    assert data["source"] == "store"
    # 命中题库不应调用 LLM
    assert mock_llm == []


def test_search_post_hit(client, mock_llm):
    _seed_one()
    r = client.post("/search", json={"title": "1+1 等于多少？", "type": "single", "options": ["1", "2", "3", "4"]})
    assert r.json()["code"] == 1 and r.json()["answer"] == "2"


def test_search_miss_uses_llm(client, mock_llm):
    r = client.get("/search", params={"title": "1+1 是多少", "type": "single", "options": "1\n2\n3\n4"})
    data = r.json()
    assert data["code"] == 1
    assert data["source"] == "llm"
    assert data["answer_status"] == "candidate"
    assert len(mock_llm) == 1


def test_encoding_chinese_space_hash(client, mock_llm):
    # title 含中文、空格、#；应正确传入 pipeline
    title = "下列关于 C++ 的#说法 正确的是？"
    r = client.get("/search", params={"title": title, "type": "single", "options": "A\nB"})
    assert r.status_code == 200
    # 未命中，走 mock llm；确认 mock 收到原题
    assert mock_llm and mock_llm[0]["title"] == title
