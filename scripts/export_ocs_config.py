"""生成可粘贴进 OCS 的 AnswererWrapper 题库配置 JSON。

用法：python -m scripts.export_ocs_config --host 192.168.1.10 --port 8000 --trust prefer_trusted
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_config(host: str, port: int, trust: str) -> list[dict]:
    base = f"http://{host}:{port}"
    handler = (
        "return (res)=> (res && res.code===1) ? [res.question, res.answer] : "
        "(res && res.msg ? [res.msg, undefined] : undefined)"
    )
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
            "handler": handler,
        }
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--trust", default="prefer_trusted", choices=["trusted_only", "prefer_trusted", "allow_candidate"])
    args = ap.parse_args()
    cfg = build_config(args.host, args.port, args.trust)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    print(text)
    out = Path(__file__).resolve().parent.parent / "ocs_config.generated.json"
    out.write_text(text, encoding="utf-8")
    print(f"\n# 已写入 {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
