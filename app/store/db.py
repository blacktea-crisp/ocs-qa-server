"""SQLite 连接、建表、WAL。线程本地连接，适配 FastAPI 多线程。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import get_settings

_local = threading.local()

# 测试可用 set_db_override() 指定统一的 DB 文件路径，供所有线程一致使用
_db_override: str | None = None


def set_db_override(path: str | None) -> None:
    global _db_override
    _db_override = path

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    qkey         TEXT PRIMARY KEY,
    question_raw TEXT NOT NULL,
    question_norm TEXT NOT NULL,
    type         TEXT NOT NULL,
    options_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    qkey         TEXT NOT NULL,
    answer       TEXT NOT NULL,
    source       TEXT NOT NULL,
    status       TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 0,
    hit_count    INTEGER NOT NULL DEFAULT 0,
    verified_at  TEXT,
    candidates_json TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (qkey) REFERENCES questions(qkey)
);
CREATE INDEX IF NOT EXISTS idx_answers_qkey ON answers(qkey);
CREATE INDEX IF NOT EXISTS idx_answers_status ON answers(status);

CREATE TABLE IF NOT EXISTS request_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT NOT NULL UNIQUE,
    title         TEXT,
    type          TEXT,
    options       TEXT,
    images_count  INTEGER DEFAULT 0,
    store_hit     INTEGER DEFAULT 0,
    store_answer_id INTEGER,
    trust_mode    TEXT,
    llm_provider  TEXT,
    llm_model     TEXT,
    final_answer  TEXT,
    answer_status TEXT,
    latency_ms    INTEGER DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cost_estimate REAL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON request_logs(created_at);

CREATE TABLE IF NOT EXISTS request_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    stage       TEXT NOT NULL,
    input_json  TEXT,
    output_json TEXT,
    latency_ms  INTEGER DEFAULT 0,
    ok          INTEGER DEFAULT 1,
    error       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_steps_req ON request_steps(request_id, seq);

CREATE TABLE IF NOT EXISTS settings_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        if _db_override is not None:
            path = _db_override
        else:
            path = str(get_settings().db_file)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
    return conn


def init_db(db_path: str | None = None) -> None:
    """初始化数据库（建表）。可由测试传入自定义路径。"""
    if db_path is not None:
        # 测试用独立连接，不写 thread-local
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()
        return
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
