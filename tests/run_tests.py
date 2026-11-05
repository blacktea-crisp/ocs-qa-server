"""零第三方依赖的测试运行器（标准库 unittest）。

本机网络受限无法 pip 安装 pytest，故提供本运行器作为实际验证手段；
tests/*.py 中的 pytest 版本作为标准参考保留。

运行：python tests/run_tests.py [-v]
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fresh_db():
    """为每个测试重置到独立临时 DB（用全局 override，保证所有线程一致）。"""
    from app.store import db as dbmod

    dbfile = Path(tempfile.mkdtemp()) / "test.db"
    dbmod.set_db_override(str(dbfile))
    # 清掉当前线程可能缓存的旧连接
    if getattr(dbmod._local, "conn", None) is not None:
        try:
            dbmod._local.conn.close()
        except Exception:
            pass
    dbmod._local.conn = None
    dbmod.init_db()  # 通过 get_conn（走 override）建表
    return None


class BaseCase(unittest.TestCase):
    def setUp(self):
        _fresh_db()
        from app.config import get_settings

        self.s = get_settings()
        self._saved = {
            "admin_token": self.s.admin_token,
            "enable_llm": self.s.enable_llm,
            "enable_vision": self.s.enable_vision,
            "default_answer_trust": self.s.default_answer_trust,
            "similarity_threshold": self.s.similarity_threshold,
        }
        self.s.admin_token = ""
        self.s.enable_llm = True
        self.s.enable_vision = True
        self.s.default_answer_trust = "prefer_trusted"
        self.s.similarity_threshold = 0.75

        from fastapi.testclient import TestClient

        from app.main import app

        self.client = TestClient(app)

        # mock LLM
        self.llm_calls = []

        def fake_answer(title, qtype, options):
            self.llm_calls.append({"title": title, "type": qtype, "options": options})
            if "1+1" in title:
                ans = "2"
            elif qtype == "multiple":
                ans = "#".join(options[:2]) if options else ""
            elif qtype == "judgement":
                ans = "正确"
            elif qtype == "completion":
                ans = "H2O"
            else:
                ans = options[0] if options else "LLM答案"
            return ans, {"prompt_tokens": 10, "completion_tokens": 5, "model": "mock", "_prompt": title, "_raw": ans}

        self._p1 = mock.patch("app.llm.answerer.answer", fake_answer)
        self._p1.start()

        # mock vision
        self.vision_calls = []

        def fake_recognize(title, options, images=None):
            self.vision_calls.append({"title": title, "options": options, "images": images})
            return "图片识别内容", {"prompt_tokens": 20, "completion_tokens": 8, "model": "mock-vl"}, ["http://example.com/a.png"]

        self._p2 = mock.patch("app.llm.vision.recognize", fake_recognize)
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()
        for k, v in self._saved.items():
            setattr(self.s, k, v)
        from app.store import db as dbmod

        dbmod.set_db_override(None)
        if getattr(dbmod._local, "conn", None) is not None:
            try:
                dbmod._local.conn.close()
            except Exception:
                pass
        dbmod._local.conn = None


from app.store import repository as repo  # noqa: E402
from app.store.models import AnswerSource, AnswerStatus  # noqa: E402


class TestSearch(BaseCase):
    def _seed(self, title="1+1 等于多少？", qtype="single", opts=("1", "2", "3", "4"), ans="2"):
        o = list(opts)
        qk = repo.compute_qkey(title, o, qtype)
        repo.upsert_question(qk, title, repo.normalize(title), qtype, o)
        repo.upsert_answer(qk, ans, AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
        return qk

    def test_health(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")

    def test_get_hit(self):
        self._seed()
        r = self.client.get("/search", params={"title": "1+1 等于多少？", "type": "single", "options": "1\n2\n3\n4"})
        d = r.json()
        self.assertEqual(d["code"], 1)
        self.assertEqual(d["answer"], "2")
        self.assertEqual(d["source"], "store")
        self.assertEqual(self.llm_calls, [])

    def test_post_hit(self):
        self._seed()
        r = self.client.post("/search", json={"title": "1+1 等于多少？", "type": "single", "options": ["1", "2", "3", "4"]})
        self.assertEqual(r.json()["answer"], "2")

    def test_miss_uses_llm(self):
        r = self.client.get("/search", params={"title": "1+1 是多少", "type": "single", "options": "1\n2\n3\n4"})
        d = r.json()
        self.assertEqual(d["code"], 1)
        self.assertEqual(d["source"], "llm")
        self.assertEqual(d["answer_status"], "candidate")
        self.assertEqual(len(self.llm_calls), 1)

    def test_encoding(self):
        title = "下列关于 C++ 的#说法 正确的是？"
        r = self.client.get("/search", params={"title": title, "type": "single", "options": "A\nB"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.llm_calls[0]["title"], title)


class TestSameTitleDiffOptions(BaseCase):
    def test_independent(self):
        title = "以下哪个是正确的？"

        def fake1(t, qtype, options):
            return options[0], {"prompt_tokens": 1, "completion_tokens": 1, "model": "mock", "_raw": options[0]}

        with mock.patch("app.llm.answerer.answer", fake1):
            r1 = self.client.post("/search", json={"title": title, "type": "single", "options": ["选项甲", "选项乙"]})
        self.assertEqual(r1.json()["answer"], "选项甲")

        def fake2(t, qtype, options):
            return options[1], {"prompt_tokens": 1, "completion_tokens": 1, "model": "mock", "_raw": options[1]}

        with mock.patch("app.llm.answerer.answer", fake2):
            r2 = self.client.post("/search", json={"title": title, "type": "single", "options": ["苹果", "香蕉"]})
        self.assertEqual(r2.json()["answer"], "香蕉")

        k1 = repo.compute_qkey(title, ["选项甲", "选项乙"], "single")
        k2 = repo.compute_qkey(title, ["苹果", "香蕉"], "single")
        self.assertNotEqual(k1, k2)
        self.assertIsNotNone(repo.get_question(k1))
        self.assertIsNotNone(repo.get_question(k2))
        self.assertEqual(repo.resolve_for_trust(k1, "prefer_trusted").answer, "选项甲")
        self.assertEqual(repo.resolve_for_trust(k2, "prefer_trusted").answer, "香蕉")

    def test_option_order_insensitive(self):
        k1 = repo.compute_qkey("题目", ["A选项", "B选项"], "single")
        k2 = repo.compute_qkey("题目", ["B选项", "A选项"], "single")
        self.assertEqual(k1, k2)


class TestLLM(BaseCase):
    def test_multiple_hash(self):
        r = self.client.post("/search", json={"title": "以下哪些是编程语言？", "type": "multiple", "options": "Python\nJava\nHTML\nCSS"})
        self.assertIn("#", r.json()["answer"])
        qk = repo.compute_qkey("以下哪些是编程语言？", ["Python", "Java", "HTML", "CSS"], "multiple")
        self.assertEqual(repo.list_answers(qk)[0].status.value, "candidate")

    def test_judgement(self):
        r = self.client.post("/search", json={"title": "天是蓝的吗", "type": "judgement", "options": ["正确", "错误"]})
        self.assertIn(r.json()["answer"], ("正确", "错误"))

    def test_completion(self):
        r = self.client.post("/search", json={"title": "水的化学式", "type": "completion", "options": []})
        self.assertEqual(r.json()["code"], 1)

    def test_trusted_only_blocks(self):
        title = "只信可信题"
        self.client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"], "answer_trust": "trusted_only"})
        qk = repo.compute_qkey(title, ["A", "B"], "single")
        self.assertIsNone(repo.resolve_for_trust(qk, "trusted_only"))

    def test_prefer_trusted_candidate(self):
        title = "优先可信题"
        self.client.post("/search", json={"title": title, "type": "single", "options": ["甲", "乙"], "answer_trust": "prefer_trusted"})
        qk = repo.compute_qkey(title, ["甲", "乙"], "single")
        self.assertEqual(repo.resolve_for_trust(qk, "prefer_trusted").status.value, "candidate")

    def test_allow_candidate(self):
        title = "允许候选题"
        self.client.post("/search", json={"title": title, "type": "single", "options": ["X", "Y"], "answer_trust": "allow_candidate"})
        qk = repo.compute_qkey(title, ["X", "Y"], "single")
        self.assertIsNotNone(repo.resolve_for_trust(qk, "allow_candidate"))


class TestVision(BaseCase):
    def test_triggered(self):
        r = self.client.post("/search", json={"title": "请看图片 http://example.com/q.png", "type": "single", "options": ["A", "B"]})
        self.assertEqual(r.json()["code"], 1)
        self.assertEqual(len(self.vision_calls), 1)

    def test_not_triggered(self):
        r = self.client.post("/search", json={"title": "纯文字题目", "type": "single", "options": ["A", "B"]})
        self.assertEqual(r.json()["code"], 1)
        self.assertEqual(len(self.vision_calls), 0)

    def test_failure_degrades(self):
        def boom(title, options, images=None):
            raise RuntimeError("识图服务不可用")

        with mock.patch("app.llm.vision.recognize", boom):
            r = self.client.post("/search", json={"title": "图片题 http://example.com/x.jpg", "type": "single", "options": ["A", "B"]})
        self.assertEqual(r.json()["code"], 1)


class TestLogging(BaseCase):
    def test_two_layers(self):
        r = self.client.post("/search", json={"title": "记录测试题", "type": "single", "options": ["A", "B"]})
        rid = r.json()["request_id"]
        self.assertTrue(rid)
        log = self.client.get(f"/api/admin/logs/{rid}").json()
        self.assertEqual(log["title"], "记录测试题")
        self.assertTrue(log["final_answer"])
        steps = log["steps"]
        self.assertGreaterEqual(len(steps), 5)
        stages = [s["stage"] for s in steps]
        for st in ["receive", "normalize", "store_lookup", "finalize"]:
            self.assertIn(st, stages)
        seqs = [s["seq"] for s in steps]
        self.assertEqual(seqs, sorted(seqs))

    def test_llm_steps(self):
        r = self.client.post("/search", json={"title": "LLM记录题", "type": "single", "options": ["A", "B"]})
        rid = r.json()["request_id"]
        stages = [s["stage"] for s in self.client.get(f"/api/admin/logs/{rid}").json()["steps"]]
        self.assertIn("llm_request", stages)
        self.assertIn("llm_response", stages)
        self.assertIn("store_write", stages)

    def test_store_hit_logged(self):
        title, opts = "命中日志题", ["1", "2"]
        qk = repo.compute_qkey(title, opts, "single")
        repo.upsert_question(qk, title, repo.normalize(title), "single", opts)
        repo.upsert_answer(qk, "1", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
        rid = self.client.post("/search", json={"title": title, "type": "single", "options": opts}).json()["request_id"]
        self.assertEqual(self.client.get(f"/api/admin/logs/{rid}").json()["store_hit"], 1)


class TestAnswerVerify(BaseCase):
    def test_promote(self):
        title = "转正题"
        self.client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
        qk = repo.compute_qkey(title, ["A", "B"], "single")
        aid = repo.list_answers(qk)[0].id
        r = self.client.post(f"/api/admin/answers/{aid}/promote")
        self.assertEqual(r.json()["status"], "trusted")
        self.assertEqual(repo.get_answer(aid).status.value, "trusted")

    def test_demote(self):
        title = "降级题"
        self.client.post("/search", json={"title": title, "type": "single", "options": ["A", "B"]})
        qk = repo.compute_qkey(title, ["A", "B"], "single")
        aid = repo.list_answers(qk)[0].id
        self.client.post(f"/api/admin/answers/{aid}/promote")
        self.client.post(f"/api/admin/answers/{aid}/demote")
        self.assertEqual(repo.get_answer(aid).status.value, "candidate")

    def test_conflict(self):
        qk = repo.compute_qkey("冲突题", ["A", "B"], "single")
        repo.upsert_question(qk, "冲突题", repo.normalize("冲突题"), "single", ["A", "B"])
        repo.upsert_answer(qk, "A", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
        repo.upsert_answer(qk, "B", AnswerSource.LLM, AnswerStatus.TRUSTED, 0.6)
        statuses = [a.status.value for a in repo.list_answers(qk)]
        self.assertIn("conflict", statuses)


class TestAdminAPI(BaseCase):
    def test_auth(self):
        self.s.admin_token = "secret123"
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/dashboard", headers={"X-Admin-Token": "secret123"}).status_code, 200)

    def test_dashboard(self):
        self.client.post("/search", json={"title": "dashboard题", "type": "single", "options": ["A", "B"]})
        d = self.client.get("/api/admin/dashboard").json()
        self.assertGreaterEqual(d["total_requests"], 1)
        self.assertIn("hit_rate", d)
        self.assertIn("questions_total", d)

    def test_questions_crud(self):
        self.client.post("/search", json={"title": "CRUD题", "type": "single", "options": ["A", "B"]})
        items = self.client.get("/api/admin/questions").json()["items"]
        self.assertGreaterEqual(len(items), 1)
        qk = items[0]["qkey"]
        self.assertTrue(self.client.delete(f"/api/admin/questions/{qk}").json()["ok"])

    def test_settings(self):
        r = self.client.put("/api/admin/settings", json={"default_answer_trust": "allow_candidate"})
        self.assertTrue(r.json()["ok"])
        g = self.client.get("/api/admin/settings").json()
        self.assertEqual(g["effective"]["default_answer_trust"], "allow_candidate")


class TestProfiles(BaseCase):
    def test_crud_and_activate(self):
        r = self.client.post("/api/admin/llm/profiles", json={
            "name": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test", "model": "gpt-4o", "vision_model": "gpt-4o", "activate": True})
        pid = r.json()["id"]
        items = self.client.get("/api/admin/llm/profiles").json()["items"]
        self.assertTrue(any(i["id"] == pid for i in items))
        self.assertNotIn("api_key", items[0])
        self.assertTrue(any(i["is_active"] == 1 for i in items))
        from app.config import effective_llm
        eff = effective_llm()
        self.assertEqual(eff["model"], "gpt-4o")
        self.assertEqual(eff["base_url"], "https://api.openai.com/v1")
        self.assertEqual(eff["profile"], "OpenAI")
        r2 = self.client.post("/api/admin/llm/profiles", json={
            "name": "Local", "provider": "ollama", "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "ollama", "model": "qwen2.5:7b", "vision_model": "qwen2.5vl:7b"})
        pid2 = r2.json()["id"]
        self.client.post(f"/api/admin/llm/profiles/{pid2}/activate")
        self.assertEqual(effective_llm()["model"], "qwen2.5:7b")
        self.client.put(f"/api/admin/llm/profiles/{pid2}", json={"model": "llama3"})
        self.assertEqual(effective_llm()["model"], "llama3")
        self.assertTrue(self.client.delete(f"/api/admin/llm/profiles/{pid2}").json()["ok"])

    def test_empty_key_preserved(self):
        r = self.client.post("/api/admin/llm/profiles", json={"name": "P1", "base_url": "x", "api_key": "sk-abc", "model": "m"})
        pid = r.json()["id"]
        self.client.put(f"/api/admin/llm/profiles/{pid}", json={"api_key": "", "model": "m2"})
        from app.store import repository as repo
        self.assertEqual(repo.get_profile(pid)["api_key"], "sk-abc")


class TestLLMEndpoints(BaseCase):
    def test_test_connection_mock(self):
        with mock.patch("app.llm.client.test_connection", lambda cfg=None: {"ok": True, "model": "x", "latency_ms": 5, "reply": "OK"}):
            r = self.client.post("/api/admin/llm/test", json={})
            self.assertTrue(r.json()["ok"])

    def test_list_models_mock(self):
        with mock.patch("app.llm.client.list_models", lambda cfg=None: {"ok": True, "models": ["m1", "m2"]}):
            r = self.client.get("/api/admin/llm/models")
            self.assertEqual(r.json()["models"], ["m1", "m2"])


class TestExportAndDetail(BaseCase):
    def _seed_q(self):
        from app.store import repository as repo
        from app.store.models import AnswerSource, AnswerStatus
        qk = repo.compute_qkey("导出题", ["A", "B", "C"], "multiple")
        repo.upsert_question(qk, "导出题", repo.normalize("导出题"), "multiple", ["A", "B", "C"])
        repo.upsert_answer(qk, "A#C", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
        return qk

    def test_export_csv_json_xlsx(self):
        self._seed_q()
        for fmt in ("csv", "json", "xlsx"):
            r = self.client.get(f"/api/admin/export?format={fmt}&include_candidates=true")
            self.assertEqual(r.status_code, 200, fmt)
            self.assertGreater(len(r.content), 0)
        r = self.client.get("/api/admin/export?format=json")
        import json as _json
        data = _json.loads(r.content)
        self.assertTrue(any(d["question"] == "导出题" for d in data))

    def test_question_detail(self):
        qk = self._seed_q()
        r = self.client.get(f"/api/admin/questions/{qk}/detail")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["question_raw"], "导出题")
        self.assertEqual(len(d["options"]), 3)
        self.assertGreaterEqual(len(d["answers"]), 1)
        self.assertEqual(len(d["options_structured"]), 3)

    def test_answer_json_structured(self):
        qk = self._seed_q()
        from app.store import repository as repo
        a = repo.list_answers(qk)[0]
        self.assertEqual(a.answer_json.get("option_ids"), ["A", "C"])


class TestLogsFilter(BaseCase):
    def test_filter_and_export(self):
        self.client.post("/search", json={"title": "日志题A", "type": "single", "options": ["A", "B"]})
        r = self.client.get("/api/admin/logs?only_errors=true")
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get("/api/admin/logs?q=日志题")
        self.assertGreaterEqual(len(r2.json()["items"]), 1)
        r3 = self.client.get("/api/admin/logs/export?format=csv")
        self.assertEqual(r3.status_code, 200)
        self.assertGreater(len(r3.content), 0)


class Test021Features(BaseCase):
    def test_ocs_config_v1_v2(self):
        for v in ("v1", "v2"):
            r = self.client.get(f"/api/admin/ocs-config?version={v}&host=1.2.3.4&port=9000")
            self.assertEqual(r.status_code, 200)
            d = r.json()
            self.assertTrue(d["ok"])
            self.assertEqual(d["version"], v)
            self.assertIn("text", d)
        # v2 含 images 字段
        d = self.client.get("/api/admin/ocs-config?version=v2").json()
        self.assertIn("${images}", str(d["config"]))

    def test_log_hit_answer_info(self):
        # seed 一条题，请求命中，检查日志 hit_answer
        from app.store import repository as repo
        from app.store.models import AnswerSource, AnswerStatus
        title, opts = "命中信息题", ["A", "B"]
        qk = repo.compute_qkey(title, opts, "single")
        repo.upsert_question(qk, title, repo.normalize(title), "single", opts)
        repo.upsert_answer(qk, "A", AnswerSource.STORE, AnswerStatus.TRUSTED, 1.0)
        rid = self.client.post("/search", json={"title": title, "type": "single", "options": opts}).json()["request_id"]
        log = self.client.get(f"/api/admin/logs/{rid}").json()
        self.assertIsNotNone(log.get("hit_answer"))
        self.assertEqual(log["hit_answer"]["answer"], "A")

    def test_vision_model_filter(self):
        from app.llm.client import is_vision_model
        self.assertTrue(is_vision_model("qwen2.5vl:7b"))
        self.assertTrue(is_vision_model("gpt-4o"))
        self.assertFalse(is_vision_model("qwen2.5:7b"))
        self.assertFalse(is_vision_model("llama3"))

    def test_db_user_version(self):
        import sqlite3
        # tmp_env 设置的库已迁移
        from app.store import db as dbmod
        conn = dbmod.get_conn()
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(ver, 1)


if __name__ == "__main__":
    verbosity = 2 if "-v" in sys.argv else 1
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
