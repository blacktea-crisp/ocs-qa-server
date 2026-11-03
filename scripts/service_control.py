"""服务控制层：读写 .env、探活、启动/停止/重启后端（uvicorn）。

被 tray.py 与 tray_config.py 复用。纯标准库。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
PID_FILE = ROOT / "data" / ".tray_pids.json"
LOG_FILE = ROOT / "data" / "launcher.log"

PYTHONW = Path(sys.executable).with_name("pythonw.exe")
PYTHON = Path(sys.executable)

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


# ---------------- .env 读写 ----------------

def read_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def ensure_env() -> dict[str, str]:
    """首次使用：若 .env 不存在，从 .env.example 复制。"""
    if not ENV_PATH.exists() and ENV_EXAMPLE.exists():
        ENV_PATH.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return read_env()


def update_env(updates: dict[str, str]) -> None:
    """安全更新 .env：保留注释与顺序，替换存在的键，追加不存在的键。"""
    ensure_env()
    lines = ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    keys_done = set()
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                keys_done.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in keys_done:
            out.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def env_host() -> str:
    return read_env().get("HOST", "127.0.0.1")


def env_port() -> int:
    try:
        return int(read_env().get("PORT", "8000"))
    except ValueError:
        return 8000


def admin_token() -> str:
    return read_env().get("ADMIN_TOKEN", "")


# ---------------- 日志 ----------------

def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------- 探活 ----------------

def probe_host() -> str:
    h = env_host()
    return "127.0.0.1" if h in ("0.0.0.0", "") else h


def health_url(port: int | None = None) -> str:
    return f"http://{probe_host()}:{port or env_port()}/health"


def is_backend_alive(port: int | None = None, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(health_url(port), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def is_port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except Exception:
        return False


# ---------------- PID 记录 ----------------

def _read_pids() -> dict:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_pids(d: dict) -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


# ---------------- 运行时句柄（同进程内启停最可靠）----------------
_runtime: dict[str, subprocess.Popen] = {}


def _python_exe() -> str:
    return str(PYTHONW) if PYTHONW.exists() else str(PYTHON)


def precheck_deps() -> str | None:
    """检查后端依赖是否可导入。返回 None 表示 OK，否则返回错误信息。"""
    code = "import fastapi,uvicorn,httpx,pydantic"
    try:
        r = subprocess.run([_python_exe(), "-c", code], capture_output=True, text=True, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            return (r.stderr or "").strip() or "依赖导入失败"
        return None
    except Exception as e:
        return str(e)


def start_backend() -> dict:
    """启动后端。返回 {ok, message, pid}。"""
    port = env_port()
    if is_backend_alive(port):
        return {"ok": True, "message": "服务已在运行", "pid": _read_pids().get("backend")}
    if is_port_listening(port):
        return {"ok": False, "message": f"端口 {port} 被其他程序占用，请释放或改配置端口"}

    err = precheck_deps()
    if err:
        return {"ok": False, "message": f"依赖缺失，请先 pip install -r requirements.txt\n详情: {err}"}

    host = env_host()
    args = [_python_exe(), "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    env = os.environ.copy()
    try:
        # 用 pythonw 时无 stdout 可重定向；日志由后端自身与 app 写
        p = subprocess.Popen(
            args, cwd=str(ROOT), env=env,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _runtime["backend"] = p
        d = _read_pids()
        d["backend"] = p.pid
        _write_pids(d)
        log(f"启动后端 pid={p.pid} host={host} port={port}")
        # 等待就绪（uvicorn 冷启动可能较慢，最长 ~20s）
        for _ in range(70):
            if is_backend_alive(port):
                return {"ok": True, "message": "已启动", "pid": p.pid}
            if p.poll() is not None:
                return {"ok": False, "message": "后端进程已退出（请查看日志）", "pid": p.pid}
            time.sleep(0.3)
        return {"ok": False, "message": "已启动但健康检查超时（请查看日志）", "pid": p.pid}
    except Exception as e:
        log(f"启动后端失败: {e}")
        return {"ok": False, "message": f"启动失败: {e}"}


def _pid_alive(pid: int) -> bool:
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
        if not h:
            return False
        WAIT_TIMEOUT = 258
        rc = kernel32.WaitForSingleObject(h, 0)
        kernel32.CloseHandle(h)
        return rc == WAIT_TIMEOUT
    except Exception:
        return False


def _port_pids(port: int) -> list[str]:
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pids.append(line.split()[-1])
    except Exception:
        pass
    return pids


def stop_backend(wait: float = 8.0) -> dict:
    """停止本服务后端：优先用运行时句柄 terminate（同进程最可靠），再按端口兜底。"""
    port = env_port()
    d = _read_pids()
    pid = d.get("backend")
    killed = False

    # 1) 运行时句柄（同一进程内的父进程可直接 terminate 子进程）
    p = _runtime.get("backend")
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
            killed = True
            log(f"terminate backend pid={p.pid} rc={p.returncode}")
        except Exception as e:
            log(f"terminate 失败: {e}")
    _runtime.pop("backend", None)

    # 2) 按记录的 PID 结束（跨进程兜底，可能因权限失败）
    if not killed and pid and _pid_alive(int(pid)):
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        killed = killed or r.returncode == 0
        log(f"taskkill backend pid={pid} rc={r.returncode}")

    # 2) 兜底：循环按端口监听进程结束（应对 uvicorn 启动/子进程 pid 变化）
    deadline = time.time() + wait
    while time.time() < deadline:
        if not is_port_listening(port):
            break
        pids_now = _port_pids(port)
        if not pids_now:
            time.sleep(0.25)
            continue
        for p2 in pids_now:
            subprocess.run(["taskkill", "/PID", str(p2), "/F", "/T"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
            killed = True
            log(f"taskkill by port {port} pid={p2}")
        time.sleep(0.4)

    # 3) 再轮询确认端口真正释放（探活）
    while time.time() < deadline:
        if not is_port_listening(port) and not is_backend_alive(port):
            break
        time.sleep(0.3)

    d.pop("backend", None)
    _write_pids(d)

    if is_port_listening(port) or is_backend_alive(port):
        return {"ok": False, "message": f"停止超时：端口 {port} 仍被占用，可能被其他程序使用"}
    return {"ok": True, "message": "已停止" if killed else "服务未在运行"}


def restart_backend() -> dict:
    stop_backend()
    time.sleep(0.6)
    return start_backend()


# ---------------- 前端静态服务（可选，打开管理台时按需）----------------

ADMIN_UI_PORT = 8020


def is_admin_ui_alive() -> bool:
    return is_port_listening(ADMIN_UI_PORT)


def start_admin_ui() -> dict:
    if is_admin_ui_alive():
        return {"ok": True, "message": "前端已在运行"}
    args = [_python_exe(), "-m", "scripts.serve_admin", "--port", str(ADMIN_UI_PORT)]
    try:
        p = subprocess.Popen(args, cwd=str(ROOT), creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d = _read_pids()
        d["admin_ui"] = p.pid
        _write_pids(d)
        for _ in range(20):
            if is_admin_ui_alive():
                return {"ok": True, "message": "前端已启动", "pid": p.pid}
            time.sleep(0.2)
        return {"ok": False, "message": "前端启动超时"}
    except Exception as e:
        return {"ok": False, "message": f"前端启动失败: {e}"}


def stop_admin_ui() -> None:
    d = _read_pids()
    pid = d.get("admin_ui")
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        d.pop("admin_ui", None)
        _write_pids(d)


# ---------------- Supervisor 客户端（方案A：后端启停统一交给 supervisor）----------------

SUPERVISOR_PORT = 8010


def supervisor_url(path: str) -> str:
    return f"http://127.0.0.1:{SUPERVISOR_PORT}{path}"


def is_supervisor_alive(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(supervisor_url("/ping"), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_supervisor() -> dict:
    """确保 supervisor 在运行（它负责托管后端）。"""
    if is_supervisor_alive():
        return {"ok": True, "message": "supervisor 已在运行"}
    args = [_python_exe(), "-m", "scripts.supervisor",
            "--port", str(SUPERVISOR_PORT), "--backend-port", str(env_port())]
    try:
        p = subprocess.Popen(args, cwd=str(ROOT),
                             creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        d = _read_pids()
        d["supervisor"] = p.pid
        _write_pids(d)
        log(f"启动 supervisor pid={p.pid}")
        for _ in range(30):
            if is_supervisor_alive():
                return {"ok": True, "message": "supervisor 已启动", "pid": p.pid}
            time.sleep(0.2)
        return {"ok": False, "message": "supervisor 启动超时"}
    except Exception as e:
        return {"ok": False, "message": f"supervisor 启动失败: {e}"}


def _sup_call(path: str, method: str = "GET", timeout: float = 40.0) -> dict:
    """调用 supervisor 接口。返回 {ok,message,...}。"""
    try:
        req = urllib.request.Request(supervisor_url(path), method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "message": f"supervisor 调用失败: {e}"}


def sup_status() -> dict:
    if not is_supervisor_alive():
        return {"backend_alive": is_backend_alive(), "managed_pid": None,
                "uptime_s": None, "backend_port": env_port(), "supervisor": False}
    r = _sup_call("/api/admin/service/status")
    r["supervisor"] = True
    return r


def sup_start_backend() -> dict:
    s = start_supervisor()
    if not s.get("ok"):
        return s
    return _sup_call("/api/admin/service/start", "POST")


def sup_stop_backend() -> dict:
    if not is_supervisor_alive():
        return {"ok": True, "message": "supervisor 未运行，服务未在管理"}
    return _sup_call("/api/admin/service/stop", "POST")


def sup_restart_backend() -> dict:
    s = start_supervisor()
    if not s.get("ok"):
        return s
    return _sup_call("/api/admin/service/restart", "POST")


def sup_shutdown() -> dict:
    """关闭 supervisor 自身（连带停后端）。"""
    if not is_supervisor_alive():
        return {"ok": True, "message": "supervisor 未运行"}
    r = _sup_call("/shutdown", "POST", timeout=10)
    # 清理 pid 记录
    d = _read_pids()
    d.pop("supervisor", None)
    _write_pids(d)
    return r
