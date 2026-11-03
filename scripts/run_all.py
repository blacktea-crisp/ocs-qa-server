"""一键启动三进程：后端 + 管理台前端 + supervisor（各自子进程，Ctrl+C 统一退出）。

用法：python scripts/run_all.py
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
procs: list[subprocess.Popen] = []


def spawn(args: list[str]) -> subprocess.Popen:
    print(f"[run_all] 启动: {' '.join(args)}")
    p = subprocess.Popen(args, cwd=str(ROOT))
    procs.append(p)
    return p


def main() -> None:
    py = sys.executable
    spawn([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"])
    time.sleep(2)
    spawn([py, "-m", "scripts.serve_admin", "--port", "8020"])
    spawn([py, "-m", "scripts.supervisor", "--port", "8010", "--backend-port", "8000"])
    print("\n[run_all] 已启动：")
    print("  后端      http://127.0.0.1:8000/docs")
    print("  管理台    http://127.0.0.1:8020/")
    print("  supervisor http://127.0.0.1:8010/api/admin/service/status")
    print("按 Ctrl+C 退出全部。\n")
    try:
        while True:
            time.sleep(1)
            for p in procs:
                if p.poll() is not None:
                    print(f"[run_all] 子进程退出 code={p.returncode}")
                    procs.remove(p)
                    break
    except KeyboardInterrupt:
        print("\n[run_all] 正在停止…")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
