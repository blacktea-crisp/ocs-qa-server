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

-- 题型注册表（内置四种 + unknown；预留扩展：新题型插一行 + 定义 answer_schema）
CREATE TABLE IF NOT EXISTS question_types (
    code          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    answer_schema TEXT NOT NULL DEFAULT '{}',
    enabled       INTEGER NOT NULL DEFAULT 1
);

-- 选项独立表（替代裸 options_json；questions.options_json 保留为快照兼容）
CREATE TABLE IF NOT EXISTS options (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    qkey     TEXT NOT NULL,
    idx      INTEGER NOT NULL,
    content  TEXT NOT NULL,
    is_image INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (qkey) REFERENCES questions(qkey)
);
CREATE INDEX IF NOT EXISTS idx_options_qkey ON options(qkey);

-- 提供商配置档案（多套 LLM 配置，可命名/编辑/删除/切换）
CREATE TABLE IF NOT EXISTS llm_profiles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    provider   TEXT NOT NULL DEFAULT 'custom',
    base_url   TEXT NOT NULL DEFAULT '',
    api_key    TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    vision_model TEXT NOT NULL DEFAULT '',
    is_active  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

# 内置题型种子（迁移时幂等插入）
QUESTION_TYPE_SEED = [
    ("single", "单选题", '{"type":"option_ids","cardinality":"1"}'),
    ("multiple", "多选题", '{"type":"option_ids","cardinality":"N"}'),
    ("judgement", "判断题", '{"type":"bool"}'),
    ("completion", "填空题", '{"type":"blanks"}'),
    ("unknown", "未知题型", '{"type":"text"}'),
]

# answers 表增量列（老库无则补）
_ANSWERS_NEW_COLUMNS = [
    ("answer_json", "TEXT"),  # 结构化答案：{option_ids:[]}|{value:bool}|{blanks:[]}|{text:""}
]


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
        conn.execute("PRAGMA busy_timeout=8000;")  # 并发写时等待而非立即报 locked
        _local.conn = conn
    return conn


# 迁移版本号（用 PRAGMA user_version 记录，避免每次启动重复全量写）
MIGRATION_VERSION = 2


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等增量迁移：补列、种子题型、回填结构化答案、回填 options 表。

    用 PRAGMA user_version 记录已迁移版本，版本达标则跳过（减少启动写锁）。
    """
    cur_ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if cur_ver >= MIGRATION_VERSION:
        return

    # 1) answers 补列
    cols = {r[1] for r in conn.execute("PRAGMA table_info(answers)").fetchall()}
    for name, decl in _ANSWERS_NEW_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE answers ADD COLUMN {name} {decl}")

    # 2) 种子题型
    for code, name, schema in QUESTION_TYPE_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO question_types(code,name,answer_schema,enabled) VALUES(?,?,?,1)",
            (code, name, schema),
        )

    # 3) 回填 options 表（从 questions.options_json，若该 qkey 尚无 options 行）
    rows = conn.execute(
        "SELECT qkey, options_json FROM questions "
        "WHERE qkey NOT IN (SELECT DISTINCT qkey FROM options)"
    ).fetchall()
    import json as _json

    for r in rows:
        try:
            opts = _json.loads(r["options_json"] or "[]")
        except Exception:
            opts = []
        for i, o in enumerate(opts):
            conn.execute(
                "INSERT INTO options(qkey,idx,content,is_image) VALUES(?,?,?,0)",
                (r["qkey"], i, str(o)),
            )

    # 4) 回填 answer_json（老库有 answer 但 answer_json 为空）
    rows = conn.execute(
        "SELECT a.id, a.answer, q.type FROM answers a JOIN questions q ON q.qkey=a.qkey "
        "WHERE a.answer_json IS NULL"
    ).fetchall()
    for r in rows:
        aj = infer_answer_json(r["answer"], r["type"])
        conn.execute("UPDATE answers SET answer_json=? WHERE id=?", (_json.dumps(aj, ensure_ascii=False), r["id"]))

    conn.execute(f"PRAGMA user_version={MIGRATION_VERSION}")
    conn.commit()


def infer_answer_json(answer: str, qtype: str) -> dict:
    """从答案文本 + 题型 反推结构化答案（供迁移与写入）。"""
    ans = (answer or "").strip()
    t = (qtype or "").strip().lower()
    if t == "multiple":
        parts = [p.strip() for p in split_answer_text(ans) if p.strip()]
        return {"option_ids": parts} if len(parts) > 1 else {"option_ids": [ans] if ans else []}
    if t == "judgement":
        low = ans.lower()
        pos = any(w in low for w in ["正确", "对", "是", "true", "t", "yes", "√", "1"])
        neg = any(w in low for w in ["错误", "错", "否", "false", "f", "no", "×", "0", "不"])
        return {"value": True if pos and not neg else (False if neg and not pos else None)}
    if t == "completion":
        parts = [p.strip() for p in split_answer_text(ans) if p.strip()]
        return {"blanks": parts if parts else ([ans] if ans else [])}
    if t == "single":
        return {"option_ids": [ans] if ans else []}
    return {"text": ans}


def split_answer_text(answer: str) -> list[str]:
    """按常见答案分隔符拆分（# | ; ； 等），与 ocsjs splitAnswer 思路一致。"""
    import re as _re

    if not answer:
        return []
    # 程序代码答案不拆 ; |
    if _re.search(r"[;|；]", answer) and _looks_like_code(answer):
        return [answer]
    parts = _re.split(r"#|===|---|###|\||;|；", answer)
    return parts


def _looks_like_code(text: str) -> bool:
    import re as _re

    # 强特征：任一命中即判定为代码（避免 ; | 被误当分隔符拆散）
    strong = [
        r"#include\s*[<\"]", r"#define\s+\w", r"\b(function|def|class|struct|typedef)\s+\w",
        r"\b(int|void|float|double|char|long|short|bool|String)\s+\w+\s*[=(;]",
        r"\bmain\s*\(", r"printf\s*\(", r"scanf\s*\(", r"cout\s*<<", r"cin\s*>>",
        r"System\.out\.", r"console\.log\s*\(", r"\breturn\b", r"\bpublic\s+",
        r"\bimport\s+[\w.*]+\s*;", r"\bpackage\s+[\w.]",
    ]
    if any(_re.search(p, text) for p in strong):
        return True
    # 弱特征：同时含 花括号块 + 分号，视为代码
    if _re.search(r"[{}]", text) and ";" in text:
        return True
    return False


def init_db(db_path: str | None = None) -> None:
    """初始化数据库（建表 + 增量迁移）。可由测试传入自定义路径。"""
    if db_path is not None:
        # 测试用独立连接，不写 thread-local
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
        conn.close()
        return
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
