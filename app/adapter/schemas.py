"""适配层数据模型（对齐 OCS AnswererWrapper 契约）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResponse(BaseModel):
    code: int = Field(1, description="1=有答案, 0=无答案")
    question: str | None = None
    answer: str | None = None
    answer_status: str | None = None  # trusted / candidate / conflict
    source: str | None = None  # store / llm
    msg: str | None = None
    request_id: str | None = None


class AdminSearchBody(BaseModel):
    title: str = ""
    type: str | None = "unknown"
    options: str | list[str] | None = None
    images: list[str] | None = None
    answer_trust: str | None = None
