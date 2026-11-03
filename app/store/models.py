"""数据结构定义（dataclass + 枚举）。与 SQLite 表结构一一对应。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


class AnswerSource(str, Enum):
    STORE = "store"
    LLM = "llm"
    MERGED = "merged"


class AnswerStatus(str, Enum):
    TRUSTED = "trusted"
    CANDIDATE = "candidate"
    CONFLICT = "conflict"


class TrustMode(str, Enum):
    TRUSTED_ONLY = "trusted_only"
    PREFER_TRUSTED = "prefer_trusted"
    ALLOW_CANDIDATE = "allow_candidate"


@dataclass
class Question:
    qkey: str  # hash(归一化题干 + 归一化选项排序 + 题型)
    question_raw: str
    question_norm: str
    type: str
    options: list[str]
    created_at: str

    def options_json(self) -> str:
        return json.dumps(self.options, ensure_ascii=False)


@dataclass
class Answer:
    id: int
    qkey: str
    answer: str
    source: AnswerSource
    status: AnswerStatus
    confidence: float
    hit_count: int
    verified_at: str | None
    created_at: str
    candidates: list[dict] = field(default_factory=list)  # [{answer,source,status,confidence,ts}]


@dataclass
class StepRecord:
    stage: str
    input: dict | None = None
    output: dict | None = None
    latency_ms: int = 0
    ok: bool = True
    error: str | None = None


@dataclass
class SearchResult:
    """pipeline 返回给适配层的结果。"""
    code: int  # 1 成功 / 0 无
    question: str | None = None
    answer: str | None = None
    answer_status: str | None = None
    source: str | None = None
    msg: str | None = None
