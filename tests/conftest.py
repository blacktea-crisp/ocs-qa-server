"""pytest fixtures：临时 SQLite、TestClient、mock LLM/vision。

关键：通过 monkeypatch 把 app.llm.answerer.answer / vision.recognize 替换为 mock，
测试完全离线。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.store import db as dbmod  # noqa: E402


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """每个测试独立 DB 文件 + 关闭鉴权 + 默认配置。"""
    dbfile = tmp_path / "test.db"
    dbmod.init_db(str(dbfile))

    # 让 get_conn 使用这个测试库：改写 thread-local 连接
    import sqlite3

    conn = sqlite3.connect(str(dbfile), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    dbmod._local.conn = conn

    s = get_settings()
    monkeypatch.setattr(s, "admin_token", "", raising=False)
    monkeypatch.setattr(s, "enable_llm", True, raising=False)
    monkeypatch.setattr(s, "enable_vision", True, raising=False)
    monkeypatch.setattr(s, "store_every_request", True, raising=False)
    monkeypatch.setattr(s, "default_answer_trust", "prefer_trusted", raising=False)
    monkeypatch.setattr(s, "similarity_threshold", 0.75, raising=False)

    yield dbfile
    conn.close()
    dbmod._local.conn = None


@pytest.fixture()
def client(tmp_env):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def mock_llm(monkeypatch):
    """mock 文本答题：根据题目返回预设答案。"""
    calls = []

    def fake_answer(title, qtype, options):
        calls.append({"title": title, "type": qtype, "options": options})
        # 简单规则
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

    from app.llm import answerer

    monkeypatch.setattr(answerer, "answer", fake_answer)
    return calls


@pytest.fixture()
def mock_vision(monkeypatch):
    """mock 识图：返回固定文字，记录调用。"""
    calls = []

    def fake_recognize(title, options):
        urls = ["http://example.com/a.png"]
        calls.append({"title": title, "options": options})
        return "图片识别：这是一个测试图片", {"prompt_tokens": 20, "completion_tokens": 8, "model": "mock-vl"}, urls

    from app.llm import vision

    monkeypatch.setattr(vision, "recognize", fake_recognize)
    return calls
