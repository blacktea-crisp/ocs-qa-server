"""识图：从题干/选项提取图片 URL，下载转 base64，调多模态模型得到文字描述/答案。"""
from __future__ import annotations

import base64
import re

import httpx

from app.config import get_settings
from app.llm.client import chat_with_image

IMAGE_URL_REGEX = re.compile(
    r"https?://[^\s一-鿿　-〿＀-￯]+?\.(?:png|jpe?g|gif|bmp|webp)(?:\?[^\s一-鿿　-〿＀-￯]*)?",
    re.IGNORECASE,
)

VISION_PROMPT = (
    "这是网课题目中的一张图片。请把图片里的文字、公式、选项等内容完整识别出来，"
    "用纯文本返回，不要解释。若有数学公式，用文本近似表达。"
)


def extract_image_urls(title: str, options: list[str]) -> list[str]:
    urls: list[str] = []
    for text in [title or "", *(options or [])]:
        for m in IMAGE_URL_REGEX.findall(text):
            if m not in urls:
                urls.append(m)
    return urls


def download_as_data_url(url: str, timeout: int = 20) -> str:
    """下载图片转 data URL；带 Referer/UA 防防盗链。失败抛异常。"""
    try:
        origin = re.match(r"(https?://[^/]+)", url)
        referer = (origin.group(1) + "/") if origin else ""
    except Exception:
        referer = ""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as c:
        resp = c.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "image/png").split(";")[0]
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{ctype};base64,{b64}"


def describe_image(data_url: str) -> tuple[str, dict]:
    settings = get_settings()
    return chat_with_image(VISION_PROMPT, data_url, model=settings.vision_model)


def recognize(title: str, options: list[str], images: list[str] | None = None) -> tuple[str, dict, list[str]]:
    """识别题干/选项中的图片。返回 (合并文字, usage聚合, 图片URL列表)。

    images: 外部直接传入的图片（OCS 图片优化传来的 data URL / URL 数组），优先处理。
    无图片时返回空文字。单张失败跳过。
    """
    images = images or []
    # 合并：来自 title/options 的 URL + 外部传入的 images
    urls = list(images) + extract_image_urls(title, options)
    # 去重
    seen = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]
    if not urls:
        return "", {}, []
    texts: list[str] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "model": get_settings().vision_model}
    for url in urls:
        try:
            # 已是 data URL 直接使用；否则下载
            data_url = url if str(url).startswith("data:") else download_as_data_url(url)
            text, usage = describe_image(data_url)
            texts.append(text)
            usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
            usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
        except Exception as e:  # 单张失败跳过
            texts.append(f"[图片识别失败: {str(url)[:60]}: {e}]")
    return "\n".join(texts), usage_total, urls
