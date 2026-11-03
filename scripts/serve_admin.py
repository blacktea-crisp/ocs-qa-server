"""托管 ocs-admin-ui 静态文件（独立进程，与后端解耦）。

用法：python -m scripts.serve_admin [--host 127.0.0.1] [--port 8020]
访问：http://127.0.0.1:8020/index.html
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "ocs-admin-ui"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    args = ap.parse_args()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(UI_DIR))
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        print(f"[admin-ui] 服务 {UI_DIR} 于 http://{args.host}:{args.port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("[admin-ui] 退出")


if __name__ == "__main__":
    main()
