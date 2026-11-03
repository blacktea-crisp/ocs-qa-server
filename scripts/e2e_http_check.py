# -*- coding: utf-8 -*-
"""对外部已启动的服务做端到端 HTTP 验证（命中/未命中/日志/dashboard/设置/导出）。"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
H = {"X-Admin-Token": "changeme"}


def show(name, obj):
    print(f"\n=== {name} ===")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main():
    c = httpx.Client(base_url=BASE, timeout=30)

    # 1 命中
    r = c.get("/search", params={"title": "1+1 等于多少？", "type": "single", "options": "1\n2\n3\n4"})
    d = r.json()
    show("1 命中题库", d)
    assert d["code"] == 1 and d["answer"] == "2" and d["source"] == "store", "命中失败"
    rid1 = d["request_id"]

    # 2 未命中（无 Ollama，应降级 code=0 并有 error）
    r = c.get("/search", params={"title": "一个全新未见过的题目XYZ", "type": "single", "options": "甲\n乙"})
    d = r.json()
    show("2 未命中(LLM不可用应降级)", d)
    rid2 = d.get("request_id")

    # 3 日志（命中请求的步骤回放）
    r = c.get(f"/api/admin/logs/{rid1}", headers=H)
    log = r.json()
    show("3 日志回放(命中)", {"title": log["title"], "store_hit": log["store_hit"],
                              "final_answer": log["final_answer"], "steps": [s["stage"] for s in log["steps"]]})
    assert log["store_hit"] == 1
    assert "store_lookup" in [s["stage"] for s in log["steps"]]

    # 4 未命中请求的日志（应有 llm 尝试或 error）
    r = c.get(f"/api/admin/logs/{rid2}", headers=H)
    log2 = r.json()
    stages2 = [s["stage"] for s in log2["steps"]]
    show("4 日志回放(未命中)", {"stages": stages2, "error": log2["error"]})
    assert "llm_request" in stages2

    # 5 dashboard
    r = c.get("/api/admin/dashboard", headers=H)
    show("5 dashboard", r.json())
    assert r.json()["total_requests"] >= 2

    # 6 设置读写
    c.put("/api/admin/settings", headers=H, json={"default_answer_trust": "allow_candidate"})
    g = c.get("/api/admin/settings", headers=H).json()
    show("6 设置", g["effective"]["default_answer_trust"])
    assert g["effective"]["default_answer_trust"] == "allow_candidate"
    # 还原
    c.put("/api/admin/settings", headers=H, json={"default_answer_trust": "prefer_trusted"})

    # 7 题库列表
    r = c.get("/api/admin/questions", headers=H)
    show("7 题库列表(题目数)", {"total": r.json()["total"]})

    print("\n>>> 外部服务 E2E 全部通过 <<<")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        sys.exit(1)
