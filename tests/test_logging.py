"""两层记录：request_logs + request_steps 完整性、按 request_id 回放。"""
from __future__ import annotations


def test_logging_two_layers(client, mock_llm):
    r = client.post("/search", json={"title": "记录测试题", "type": "single", "options": ["A", "B"]})
    data = r.json()
    rid = data["request_id"]
    assert rid

    # 通过管理 API 取日志与步骤
    log = client.get(f"/api/admin/logs/{rid}").json()
    assert log["title"] == "记录测试题"
    assert log["final_answer"]
    steps = log["steps"]
    assert len(steps) >= 5
    stages = [s["stage"] for s in steps]
    # 关键阶段都应出现
    for st in ["receive", "normalize", "store_lookup", "finalize"]:
        assert st in stages
    # seq 严格递增
    seqs = [s["seq"] for s in steps]
    assert seqs == sorted(seqs)


def test_logging_llm_steps(client, mock_llm):
    r = client.post("/search", json={"title": "LLM记录题", "type": "single", "options": ["A", "B"]})
    rid = r.json()["request_id"]
    log = client.get(f"/api/admin/logs/{rid}").json()
    stages = [s["stage"] for s in log["steps"]]
    assert "llm_request" in stages
    assert "llm_response" in stages
    assert "store_write" in stages


def test_store_hit_logged(client, mock_llm):
    from app.store import repository as repo
    from app.store.models import AnswerSource, AnswerStatus

    title = "命中日志题"
    opts = ["1", "2"]
    qkey = repo.compute_qkey(title, opts, "single")
    repo.upsert_question(qkey, title, repo.normalize(title), "single", opts)
    repo.upsert_answer(qkey, "1", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)

    r = client.post("/search", json={"title": title, "type": "single", "options": opts})
    rid = r.json()["request_id"]
    log = client.get(f"/api/admin/logs/{rid}").json()
    assert log["store_hit"] == 1
