"""独立 supervisor 进程：托管 ocs-qa-server 后端（uvicorn）的启停/重启/状态。

自身是一个极简 HTTP 服务，供管理台调用：
  POST /api/admin/service/start
  POST /api/admin/service/stop
  POST /api/admin/service/restart
  GET  /api/admin/service/status
后端崩溃时若 --auto-restart 则自动拉起。

用法：
  python -m scripts.supervisor [--port 8010] [--host 127.0.0.1] [--backend-port 8000] [--auto-restart]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_PORT = 8000
BACKEND_HOST = "127.0.0.1"
AUTO_RESTART = False
_proc: subprocess.Popen | None = None
_started_at: float | None = None


def _backend_url() -> str:
    return f"http://{BACKEND_HOST}:{BACKEND_PORT}/health"


def is_backend_alive() -> bool:
    try:
        with urllib.request.urlopen(_backend_url(), timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_backend() -> dict:
    global _proc, _started_at
    if _proc and _proc.poll() is None:
        return {"ok": True, "message": "already running", "pid": _proc.pid}
    if is_backend_alive():
        return {"ok": True, "message": "port already serving"}
    env = os.environ.copy()
    _proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _started_at = time.time()
    # 等待健康
    for _ in range(30):
        if is_backend_alive():
            return {"ok": True, "message": "started", "pid": _proc.pid}
        time.sleep(0.3)
    return {"ok": False, "message": "started but health check failed", "pid": _proc.pid}


def _port_pids(port: int) -> list[str]:
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pids.append(line.split()[-1])
    except Exception:
        pass
    return pids


def stop_backend() -> dict:
    global _proc
    killed = False
    if _proc and _proc.poll() is None:
        try:
            _proc.terminate()
            _proc.wait(timeout=8)
            killed = True
        except Exception:
            try:
                _proc.kill()
                killed = True
            except Exception:
                pass
        _proc = None
    # 兜底：按端口结束监听进程（覆盖外部启动/上一轮残留的后端）
    for _ in range(3):
        pids = _port_pids(BACKEND_PORT)
        if not pids:
            break
        for p2 in pids:
            subprocess.run(["taskkill", "/PID", p2, "/F", "/T"],
                           capture_output=True, creationflags=0x08000000)
            killed = True
        time.sleep(0.4)
    # 等端口释放
    for _ in range(20):
        if not is_backend_alive() and not _port_pids(BACKEND_PORT):
            break
        time.sleep(0.25)
    if is_backend_alive() or _port_pids(BACKEND_PORT):
        return {"ok": False, "message": f"端口 {BACKEND_PORT} 仍被占用，可能被其他程序使用"}
    return {"ok": True, "message": "stopped" if killed else "not running"}


def status_backend() -> dict:
    alive = is_backend_alive()
    return {
        "backend_alive": alive,
        "managed_pid": _proc.pid if (_proc and _proc.poll() is None) else None,
        "uptime_s": round(time.time() - _started_at, 1) if (_started_at and alive) else None,
        "backend_port": BACKEND_PORT,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        if self.path == "/api/admin/service/status":
            self._send(200, status_backend())
        elif self.path == "/ping":
            self._send(200, {"ok": True, "service": "supervisor", "backend_port": BACKEND_PORT})
        else:
            self._send(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        if self.path == "/api/admin/service/start":
            self._send(200, start_backend())
        elif self.path == "/api/admin/service/stop":
            self._send(200, stop_backend())
        elif self.path == "/api/admin/service/restart":
            stop_backend()
            time.sleep(0.5)
            self._send(200, start_backend())
        elif self.path == "/shutdown":
            # 供托盘退出时关闭 supervisor 自身；先停后端再退出
            stop_backend()
            self._send(200, {"ok": True, "message": "supervisor shutting down"})
            import threading

            def _die():
                time.sleep(0.3)
                os._exit(0)

            threading.Thread(target=_die, daemon=True).start()
        else:
            self._send(404, {"ok": False, "message": "not found"})

    def log_message(self, *args):
        pass


def main() -> None:
    global BACKEND_PORT, BACKEND_HOST, AUTO_RESTART
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--backend-host", default="127.0.0.1")
    ap.add_argument("--backend-port", type=int, default=8000)
    ap.add_argument("--auto-restart", action="store_true")
    args = ap.parse_args()

    # 未显式指定后端端口时，尝试从 .env 读取，保持与主服务一致
    backend_port = args.backend_port
    if backend_port == 8000:  # 默认值，尝试 .env 覆盖
        try:
            for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("PORT="):
                    backend_port = int(line.split("=", 1)[1].strip())
                    break
        except Exception:
            pass

    BACKEND_HOST, BACKEND_PORT, AUTO_RESTART = args.backend_host, backend_port, args.auto_restart

    print(f"[supervisor] 监听 {args.host}:{args.port}，托管后端 {BACKEND_HOST}:{BACKEND_PORT}")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("[supervisor] 退出")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
