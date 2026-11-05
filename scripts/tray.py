"""纯标准库 Windows 系统托盘程序（Win32 消息循环 + 原生弹出菜单）。

架构（方案A：统一交给 supervisor 管理后端）：
- supervisor(8010) 是后端(8000)的唯一管理者（负责启停/重启/状态）。
- 托盘负责：拉起 supervisor、通过 HTTP 调用 supervisor 启停后端、按需起前端(8020)、打开管理台、配置界面。
- 托盘退出时可连带停后端并关闭 supervisor。
这样托盘与网页管理台都通过同一套 supervisor 控制后端，不会双头冲突。

稳定性要点：所有 Win32 函数声明 64 位正确的 argtypes/restype，避免指针截断崩溃；
自建 Win32 隐藏窗口跑自己的消息循环（GetMessage/DispatchMessage），右键用原生 TrackPopupMenu。
"""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

from scripts import service_control as sc
from scripts import tray_icons

ROOT = Path(__file__).resolve().parent.parent
_TRAY_PIDFILE = ROOT / "data" / ".tray_pid"

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32


def _declare_prototypes():
    """为所有用到的 Win32 函数声明 64 位正确的 argtypes/restype，避免指针被截断。"""
    LRESULT = ctypes.c_ssize_t
    HWND = wintypes.HWND
    UINT = wintypes.UINT
    WPARAM = ctypes.c_size_t   # 64 位无符号
    LPARAM = ctypes.c_ssize_t  # 64 位有符号
    HMENU = wintypes.HMENU
    BOOL = wintypes.BOOL

    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]

    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, HWND, UINT, WPARAM, LPARAM]

    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.c_void_p]

    user32.CreateWindowExW.restype = HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        HWND, HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]

    user32.DestroyWindow.restype = BOOL
    user32.DestroyWindow.argtypes = [HWND]

    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, UINT,
                                  ctypes.c_int, ctypes.c_int, UINT]

    user32.LoadIconW.restype = wintypes.HICON
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]

    shell32.Shell_NotifyIconW.restype = BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]

    user32.CreatePopupMenu.restype = HMENU
    user32.AppendMenuW.restype = BOOL
    user32.AppendMenuW.argtypes = [HMENU, UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.DestroyMenu.restype = BOOL
    user32.DestroyMenu.argtypes = [HMENU]

    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.TrackPopupMenu.argtypes = [HMENU, UINT, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, HWND, ctypes.c_void_p]

    user32.GetCursorPos.restype = BOOL
    user32.GetCursorPos.argtypes = [ctypes.c_void_p]

    user32.SetForegroundWindow.restype = BOOL
    user32.SetForegroundWindow.argtypes = [HWND]

    user32.PostMessageW.restype = BOOL
    user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]

    user32.GetMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.c_void_p, HWND, UINT, UINT]
    user32.TranslateMessage.restype = BOOL
    user32.TranslateMessage.argtypes = [ctypes.c_void_p]
    user32.DispatchMessageW.restype = LRESULT
    user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
    user32.PostQuitMessage.restype = None
    user32.PostQuitMessage.argtypes = [ctypes.c_int]

    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, UINT]

    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.restype = BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


_declare_prototypes()

# ---- 常量 ----
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100

WS_OVERLAPPED = 0x00000000
WS_EX_TOOLWINDOW = 0x00000080
CW_USEDEFAULT = 0x80000000

# 菜单命令 ID
ID_STATUS = 1000
ID_START = 1001
ID_STOP = 1002
ID_RESTART = 1003
ID_CONFIG = 1004
ID_ADMIN = 1005
ID_LOG = 1006
ID_QUIT = 1007

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", wintypes.BYTE * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _pid_running(pid: int) -> bool:
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not h:
            return False
        rc = kernel32.WaitForSingleObject(h, 0)
        kernel32.CloseHandle(h)
        return rc == 258  # WAIT_TIMEOUT
    except Exception:
        return False


def _single_instance() -> bool:
    try:
        _TRAY_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        if _TRAY_PIDFILE.exists():
            try:
                old = int(_TRAY_PIDFILE.read_text().strip())
            except Exception:
                old = 0
            if old and old != os.getpid() and _pid_running(old):
                return False
        _TRAY_PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
        # 端口锁双保险（对象存活即占端口）
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 47999))
            s.listen(1)
            globals()["_lock_sock"] = s
        except OSError:
            try:
                s.close()
            except Exception:
                pass
        return True
    except Exception:
        return True


class TrayApp:
    def __init__(self):
        self.hwnd = None
        self.hicon = None
        self.running = True
        self._wndproc_ref = None
        self._menu = None
        self.class_name = f"OCSTrayWnd_{os.getpid()}"
        self._create_window()
        self._load_icon()
        self._add_icon()
        # 状态刷新线程
        self._poll_thread = threading.Thread(target=self._poll, daemon=True)
        self._poll_thread.start()

    # ---------- 窗口 ----------
    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._make_wndproc()
        wc.hInstance = hinst
        wc.lpszClassName = self.class_name
        # 保存引用防止 GC
        self._wc = wc
        self._wc_ref = wc
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            # 可能已注册，忽略
            pass
        # 创建普通隐藏窗口（用 WS_EX_TOOLWINDOW 不进任务栏）
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW, self.class_name, "OCS题库助手",
            WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None,
        )
        if not self.hwnd:
            raise RuntimeError("CreateWindowExW 失败")

    def _make_wndproc(self):
        def wndproc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_TRAYICON:
                    sc.log(f"托盘：收到托盘消息 lparam={lparam}")
                    if lparam == WM_RBUTTONUP:
                        self._show_menu()
                        return 0
                    if lparam == WM_LBUTTONUP or lparam == WM_LBUTTONDBLCLK:
                        self._show_menu()
                        return 0
                    return 0
                if msg == WM_COMMAND:
                    self._on_command(wparam & 0xFFFF)
                    return 0
                if msg == WM_DESTROY:
                    self._remove_icon()
                    user32.PostQuitMessage(0)
                    return 0
            except Exception:
                pass
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # 保存引用，避免回调被回收
        self._wndproc_ref = WNDPROC(wndproc)
        return self._wndproc_ref

    def _load_icon(self):
        try:
            p = tray_icons.ensure_icon()
            if p.exists():
                h = user32.LoadImageW(None, str(p), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
                if h:
                    self.hicon = h
                    return
        except Exception:
            pass
        self.hicon = user32.LoadIconW(None, ctypes.c_wchar_p(32512))

    def _nid(self, flags):
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon
        return nid

    def _add_icon(self):
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        nid.szTip = self._tip()
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _update_tip(self):
        nid = self._nid(NIF_TIP)
        nid.szTip = self._tip()
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _remove_icon(self):
        nid = self._nid(0)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _tip(self) -> str:
        try:
            alive = sc.is_backend_alive()
        except Exception:
            alive = False
        return f"OCS 题库助手 · {'运行中' if alive else '已停止'}"

    # ---------- 原生菜单 ----------
    def _show_menu(self):
        sc.log("托盘：显示右键菜单")
        try:
            alive = sc.is_backend_alive()
        except Exception:
            alive = False
        hmenu = user32.CreatePopupMenu()
        try:
            status = "● 服务运行中" if alive else "○ 服务已停止"
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED, ID_STATUS, status)
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            start_flags = MF_STRING | (MF_GRAYED if alive else 0)
            stop_flags = MF_STRING | (0 if alive else MF_GRAYED)
            user32.AppendMenuW(hmenu, start_flags, ID_START, "▶  启动服务")
            user32.AppendMenuW(hmenu, stop_flags, ID_STOP, "■  停止服务")
            user32.AppendMenuW(hmenu, MF_STRING, ID_RESTART, "↻  重启服务")
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(hmenu, MF_STRING, ID_CONFIG, "⚙  配置…")
            user32.AppendMenuW(hmenu, MF_STRING, ID_ADMIN, "🌐  打开管理台")
            user32.AppendMenuW(hmenu, MF_STRING, ID_LOG, "📄  查看日志")
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(hmenu, MF_STRING, ID_QUIT, "退出")

            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # 关键：SetForegroundWindow 才能让菜单正常弹出/消失
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(
                hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x, pt.y, 0, self.hwnd, None,
            )
            user32.PostMessageW(self.hwnd, 0x0000, 0, 0)  # WM_NULL 修补焦点
            if cmd:
                self._on_command(cmd)
        finally:
            user32.DestroyMenu(hmenu)

    def _on_command(self, cmd: int):
        sc.log(f"托盘：命令 {cmd}")
        try:
            if cmd == ID_START:
                self._do_async(lambda: sc.sup_start_backend())
            elif cmd == ID_STOP:
                self._do_async(lambda: sc.sup_stop_backend())
            elif cmd == ID_RESTART:
                self._do_async(lambda: sc.sup_restart_backend())
            elif cmd == ID_CONFIG:
                self._open_config()
            elif cmd == ID_ADMIN:
                self._open_admin()
            elif cmd == ID_LOG:
                self._open_log()
            elif cmd == ID_QUIT:
                self.quit()
        except Exception as e:
            sc.log(f"命令 {cmd} 失败: {e}")
            self._err("操作失败", str(e))

    def _do_async(self, fn):
        def run():
            try:
                r = fn()
                self._update_tip()
                if isinstance(r, dict) and not r.get("ok", True):
                    self._err("操作", r.get("message", "未知错误"))
            except Exception as e:
                self._err("操作", str(e))
        threading.Thread(target=run, daemon=True).start()

    # ---------- 动作 ----------
    def _open_config(self):
        # tkinter 窗口必须在有 mainloop 的主线程运行；托盘进程是纯 Win32 消息循环、无 tkinter loop，
        # 故配置界面用【独立进程】启动，避免 "main thread is not in main loop"。
        def run():
            try:
                import subprocess

                from scripts import service_control as _sc

                pyw = str(_sc.PYTHONW) if _sc.PYTHONW.exists() else str(_sc.PYTHON)
                subprocess.Popen(
                    [pyw, "-m", "scripts.tray_config"],
                    cwd=str(ROOT),
                    creationflags=0x08000000 | 0x00000008,  # CREATE_NO_WINDOW | DETACHED
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                self._err("打开配置", str(e))
        threading.Thread(target=run, daemon=True).start()

    def _open_admin(self):
        def run():
            try:
                # 确保 supervisor（托管后端）在跑，再起前端，打开浏览器
                if not sc.is_backend_alive():
                    sc.sup_start_backend()
                sc.start_admin_ui()
                webbrowser.open(f"http://127.0.0.1:{sc.ADMIN_UI_PORT}/")
            except Exception as e:
                self._err("打开管理台", str(e))
        threading.Thread(target=run, daemon=True).start()

    def _open_log(self):
        try:
            if sc.LOG_FILE.exists():
                os.startfile(str(sc.LOG_FILE))
            else:
                self._info("日志", "暂无日志文件")
        except Exception as e:
            self._err("查看日志", str(e))

    def _info(self, title, msg):
        try:
            user32.MessageBoxW(None, msg, title, 0x40)
        except Exception:
            pass

    def _err(self, title, msg):
        try:
            user32.MessageBoxW(None, msg, title, 0x10)
        except Exception:
            pass

    def quit(self):
        try:
            alive = sc.is_backend_alive()
            sup = sc.is_supervisor_alive()
            if alive or sup:
                r = user32.MessageBoxW(
                    None,
                    "后端服务/supervisor 仍在运行，是否同时停止并退出？",
                    "退出", 0x04 | 0x40,
                )
                if r == 6:  # IDYES
                    sc.sup_stop_backend()
                    sc.stop_admin_ui()
                    sc.sup_shutdown()
        except Exception:
            pass
        self.running = False
        try:
            self._remove_icon()
        except Exception:
            pass
        try:
            if _TRAY_PIDFILE.exists():
                _TRAY_PIDFILE.unlink()
        except Exception:
            pass
        user32.DestroyWindow(self.hwnd)
        user32.PostQuitMessage(0)

    def _poll(self):
        while self.running:
            try:
                self._update_tip()
            except Exception:
                pass
            time.sleep(5)

    # ---------- 消息循环 ----------
    def run(self):
        msg = wintypes.MSG()
        # GetMessageW 返回 >0 继续，0 退出
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    if "--selftest" in sys.argv:
        sc.ensure_env()
        print("start:", sc.start_backend())
        print("alive:", sc.is_backend_alive())
        print("stop:", sc.stop_backend())
        time.sleep(0.5)
        print("after:", sc.is_backend_alive(), "port:", sc.is_port_listening(8000))
        return

    if not _single_instance():
        sc.log("检测到已有实例，本次退出")
        return

    sc.ensure_env()
    sc.log("托盘程序启动（Win32 消息循环）")
    try:
        app = TrayApp()
        app.run()
    except Exception as e:
        sc.log(f"托盘异常退出: {e}")
        try:
            user32.MessageBoxW(None, f"托盘启动失败：{e}", "错误", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    main()
