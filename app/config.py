"""全局配置（pydantic-settings）。所有可调项来自环境变量 / .env。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    admin_token: str = ""  # 空则不校验
    cors_origins: str = "*"

    # 数据库
    db_path: str = "data/ocs_qa.db"

    # 大模型（OpenAI 兼容）
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"
    vision_model: str = "qwen2.5vl:7b"
    llm_timeout: int = 60

    # 信任策略默认
    default_answer_trust: str = "prefer_trusted"

    # 行为开关
    store_every_request: bool = True
    enable_llm: bool = True
    enable_vision: bool = True
    similarity_threshold: float = 0.75

    @property
    def db_file(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def effective_llm() -> dict:
    """运行期有效的 LLM 配置：激活的 provider 档案 > settings_kv > .env。

    优先级（0.2.0）：
      1. 激活的 llm_profiles 档案（若存在且字段非空）
      2. settings_kv（网页/托盘保存的单项设置）
      3. .env / 代码默认
    """
    s = get_settings()
    stored = {}
    active = None
    try:
        from app.store import repository as repo

        stored = repo.all_settings()
        active = repo.get_active_profile()
    except Exception:
        stored = {}

    def pick(key: str, default, profile_key: str | None = None):
        if active:
            pk = profile_key or key
            v = active.get(pk)
            if v not in (None, ""):
                return v
        v = stored.get(key)
        if v not in (None, ""):
            return v
        return default

    return {
        "provider": pick("llm_provider", s.llm_provider, "provider"),
        "base_url": pick("llm_base_url", s.llm_base_url, "base_url"),
        "api_key": pick("llm_api_key", s.llm_api_key, "api_key"),
        "model": pick("llm_model", s.llm_model, "model"),
        "vision_model": pick("vision_model", s.vision_model, "vision_model"),
        "timeout": s.llm_timeout,
        "profile": active.get("name") if active else None,
    }
