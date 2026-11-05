"""生成可粘贴进 OCS 的 AnswererWrapper 题库配置 JSON。

支持两种版本：
- v1（纯文本）：GET 请求，最简，不含识图。
- v2（含识图，默认）：POST 请求，data 引用 ${images}/${suggestion_title}/${suggestion_options}，
  满足 ocsjs「支持识图」判定（method=post 且引用图片字段）。

用法：
  python -m scripts.export_ocs_config --host 192.168.1.10 --port 8000 --trust prefer_trusted
  python -m scripts.export_ocs_config --version v1      # 导出纯文本版
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 响应解析器：code=1 返回 [题目,答案]，否则返回提示/undefined
HANDLER = (
    "return (res)=> (res && res.code===1) ? [res.question, res.answer] : "
    "(res && res.msg ? [res.msg, undefined] : undefined)"
)


def build_v1(host: str, port: int, trust: str) -> list[dict]:
    base = f"http://{host}:{port}"
    return [
        {
            "name": "自建题库",
            "homepage": base,
            "url": f"{base}/search",
            "method": "get",
            "responseType": "json",
            "data": {
                "title": "${title}",
                "type": "${type}",
                "options": "${options}",
                "answer_trust": trust,
            },
            "handler": HANDLER,
        }
    ]


def build_v2(host: str, port: int, trust: str) -> list[dict]:
    """v2：POST + 引用图片优化字段，OCS 判定为支持识图。"""
    base = f"http://{host}:{port}"
    return [
        {
            "name": "自建题库(含识图)",
            "homepage": base,
            "url": f"{base}/search",
            "method": "post",
            "v": 2,
            "responseType": "json",
            "headers": {"Content-Type": "application/json"},
            "data": {
                "title": "${title}",
                "type": "${type}",
                "options": "${options}",
                "answer_trust": trust,
                # 图片题优化字段：引用后 OCS 才会把图片数据/建议文本提交上来
                "images": "${images}",
                "suggestion_title": "${suggestion_title}",
                "suggestion_options": "${suggestion_options}",
            },
            "handler": HANDLER,
        }
    ]


def build_config(host: str, port: int, trust: str, version: str = "v2") -> list[dict]:
    return build_v1(host, port, trust) if version == "v1" else build_v2(host, port, trust)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--trust", default="prefer_trusted", choices=["trusted_only", "prefer_trusted", "allow_candidate"])
    ap.add_argument("--version", default="v2", choices=["v1", "v2"], help="v1=纯文本, v2=含识图(默认)")
    args = ap.parse_args()
    cfg = build_config(args.host, args.port, args.trust, args.version)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    print(text)
    out = Path(__file__).resolve().parent.parent / "ocs_config.generated.json"
    out.write_text(text, encoding="utf-8")
    print(f"\n# [{args.version}] 已写入 {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
