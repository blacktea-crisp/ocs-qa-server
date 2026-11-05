"""OpenAI 兼容客户端封装。本地(Ollama/vLLM)与云端共用同一份代码，改配置即可切换。

对外提供：
- chat(messages, model=None) -> (text, usage_dict)
- chat_with_image(text_prompt, image_data_url, model=None)
可被测试 monkeypatch 替换（见 tests/conftest.py 的 mock）。
"""
from __future__ import annotations

from typing import Any

from app.config import effective_llm


def _client():
    from openai import OpenAI

    cfg = effective_llm()
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg["timeout"])


def test_connection(cfg: dict | None = None) -> dict:
    """发一次极简 chat 验证连通性。返回 {ok, model, latency_ms, reply, error}。"""
    import time

    cfg = cfg or effective_llm()
    t0 = time.time()
    try:
        from openai import OpenAI

        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=min(cfg.get("timeout", 60), 30))
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": "回复：OK"}],
            max_tokens=8,
            temperature=0,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {
            "ok": True,
            "model": cfg["model"],
            "latency_ms": int((time.time() - t0) * 1000),
            "reply": reply[:80],
        }
    except Exception as e:
        return {
            "ok": False,
            "model": cfg.get("model"),
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e)[:300],
        }


def list_models(cfg: dict | None = None) -> dict:
    """获取 provider 支持的模型列表（OpenAI 兼容 GET /models）。返回 {ok, models[], error}。"""
    cfg = cfg or effective_llm()
    try:
        from openai import OpenAI

        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=20)
        resp = client.models.list()
        ids = []
        for m in resp.data:
            mid = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
            if mid:
                ids.append(mid)
        return {"ok": True, "models": sorted(set(ids))}
    except Exception as e:
        return {"ok": False, "models": [], "error": str(e)[:300]}


def chat(messages: list[dict], model: str | None = None) -> tuple[str, dict]:
    """纯文本对话。返回 (文本, usage)。"""
    cfg = effective_llm()
    client = _client()
    resp = client.chat.completions.create(
        model=model or cfg["model"],
        messages=messages,
        temperature=0.1,
    )
    text = resp.choices[0].message.content or ""
    usage = {
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0,
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0,
        "model": model or cfg["model"],
    }
    return text, usage


def chat_with_image(text_prompt: str, image_data_url: str, model: str | None = None) -> tuple[str, dict]:
    """多模态对话：文本 + 一张图片（data URL 或 http URL）。"""
    cfg = effective_llm()
    client = _client()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    resp = client.chat.completions.create(
        model=model or cfg["vision_model"],
        messages=messages,
        temperature=0.1,
    )
    text = resp.choices[0].message.content or ""
    usage = {
        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0,
        "completion_tokens": getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0,
        "model": model or cfg["vision_model"],
    }
    return text, usage
