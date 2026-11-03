"""管理 API 数据模型。"""
from __future__ import annotations

from pydantic import BaseModel


class AnswerCandidateIn(BaseModel):
    answer: str
    confidence: float = 1.0
    make_trusted: bool = False


class SettingsUpdate(BaseModel):
    # 任意 key-value，落 settings_kv，并即时影响行为
    default_answer_trust: str | None = None
    enable_llm: bool | None = None
    enable_vision: bool | None = None
    store_every_request: bool | None = None
    llm_model: str | None = None
    vision_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
