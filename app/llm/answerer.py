"""文本答题：构造提示词、调用 LLM、解析与校验；多选答案用 # 连接。"""
from __future__ import annotations

import re

from app.llm.client import chat

TYPE_CN = {
    "single": "单选题",
    "multiple": "多选题",
    "judgement": "判断题",
    "completion": "填空题",
    "unknown": "题目",
}

SYSTEM_PROMPT = (
    "你是一个严谨的网课题库答题助手。根据用户提供的题目、题型与选项，给出正确答案。"
    "只输出答案本身，不要解释。规则："
    "单选题只输出一个选项内容（与原选项文字一致，或一个字母）；"
    "多选题输出所有正确选项内容，用 # 连接（例如 选项A#选项C）；"
    "判断题输出 正确 或 错误；"
    "填空题输出要填入的内容，多个空用 # 连接。"
)


def build_prompt(title: str, qtype: str, options: list[str]) -> str:
    type_cn = TYPE_CN.get((qtype or "").lower(), "题目")
    lines = [f"题型：{type_cn}", f"题目：{title}"]
    if options:
        lines.append("选项：")
        for i, o in enumerate(options):
            lines.append(f"  {chr(65 + i)}. {o}")
    return "\n".join(lines)


def parse_answer(raw: str, qtype: str) -> str:
    """把模型原始输出清洗成规范答案。"""
    text = (raw or "").strip()
    # 去掉常见前缀/引号
    text = re.sub(r"^(答案[:：]?\s*)", "", text)
    text = text.strip().strip('"\'“”‘’')
    if (qtype or "").lower() == "judgement":
        low = text.lower()
        if any(w in low for w in ["正确", "对", "是", "true", "t", "yes", "√", "1"]):
            return "正确"
        if any(w in low for w in ["错误", "错", "否", "false", "f", "no", "×", "0", "不"]):
            return "错误"
    if (qtype or "").lower() == "multiple":
        # 若已是数组形式则重新用 # 连接
        if text.startswith("[") and text.endswith("]"):
            import json as _json

            try:
                arr = _json.loads(text)
                if isinstance(arr, list):
                    return "#".join(str(x).strip() for x in arr if str(x).strip())
            except Exception:
                pass
    return text


def answer(title: str, qtype: str, options: list[str]) -> tuple[str, dict]:
    """返回 (清洗后的答案, usage)。"""
    prompt = build_prompt(title, qtype, options)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw, usage = chat(messages)
    return parse_answer(raw, qtype), {**usage, "_prompt": prompt, "_raw": raw}
