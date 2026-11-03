"""托盘自带配置界面（tkinter/ttk，美观分组）。

可配置：端口、监听地址、大模型(provider/base_url/model/vision_model/api_key)、
行为开关(enable_llm/enable_vision/default_answer_trust/similarity_threshold)。
基础项写回 .env；运行期可热更新项尽量走后端 settings API。
"""
from __future__ import annotations

import json
import tkinter as tk
import urllib.request
from tkinter import messagebox, ttk

from scripts import service_control as sc

# 配色（与网页管理台呼应）
C_BG = "#0f1420"
C_PANEL = "#171f2f"
C_PANEL2 = "#1e2a3e"
C_TEXT = "#dce5f5"
C_MUTED = "#8fa3c4"
C_ACCENT = "#4f8cff"
C_GREEN = "#35c07a"
C_RED = "#ff5c6c"

TRUST_OPTIONS = [
    ("prefer_trusted", "优先可信（没可信用候选）"),
    ("trusted_only", "只信可信"),
    ("allow_candidate", "候选也直接用"),
]


class ConfigWindow:
    def __init__(self, root: tk.Tk | None = None):
        self._own_root = root is None
        self.root = root or tk.Tk()
        self.root.title("OCS 题库助手 · 配置")
        self.root.configure(bg=C_BG)
        self.root.resizable(False, False)
        self._style()
        self._build()
        self._load()
        self._center(560, 640)
        if self._own_root:
            self.root.mainloop()

    # ---------- 样式 ----------
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TFrame", background=C_BG)
        st.configure("Card.TLabelframe", background=C_PANEL, bordercolor=C_PANEL2,
                     relief="solid", borderwidth=1)
        st.configure("Card.TLabelframe.Label", background=C_PANEL, foreground=C_ACCENT,
                     font=("Microsoft YaHei", 10, "bold"))
        st.configure("TLabel", background=C_PANEL, foreground=C_TEXT, font=("Microsoft YaHei", 9))
        st.configure("Muted.TLabel", background=C_PANEL, foreground=C_MUTED, font=("Microsoft YaHei", 8))
        st.configure("TEntry", fieldbackground=C_PANEL2, foreground=C_TEXT, insertcolor=C_TEXT)
        st.configure("TCombobox", fieldbackground=C_PANEL2, foreground=C_TEXT)
        st.configure("Accent.TButton", background=C_ACCENT, foreground="#fff",
                     font=("Microsoft YaHei", 10, "bold"), borderwidth=0, padding=8)
        st.map("Accent.TButton", background=[("active", "#3f78e0")])
        st.configure("Ghost.TButton", background=C_PANEL2, foreground=C_TEXT,
                     font=("Microsoft YaHei", 9), borderwidth=0, padding=6)

    def _card(self, parent, title):
        return ttk.LabelFrame(parent, text="  " + title + "  ", style="Card.TLabelframe")

    def _row(self, parent, label, widget, hint=None):
        f = ttk.Frame(parent)
        f.pack(fill="x", padx=14, pady=6)
        ttk.Label(f, text=label, width=14).pack(side="left")
        widget.pack(side="left", fill="x", expand=True)
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").pack(fill="x", padx=28, pady=(0, 2))
        return widget

    # ---------- 界面 ----------
    def _build(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=14, pady=12)

        # 标题
        ttk.Label(self.root, text="⚙  OCS 题库助手配置", background=C_BG, foreground=C_TEXT,
                  font=("Microsoft YaHei", 13, "bold")).pack(pady=(14, 4))
        ttk.Label(self.root, text="修改后点保存；标注【需重启】的项保存后需重启服务生效",
                  background=C_BG, foreground=C_MUTED, font=("Microsoft YaHei", 8)).pack()

        # 服务
        svc = self._card(outer, "服务")
        svc.pack(fill="x", pady=6)
        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar()
        host_cb = ttk.Combobox(svc, textvariable=self.var_host, values=["127.0.0.1", "0.0.0.0"])
        self._row(svc, "监听地址", host_cb)
        self.lbl_host_warn = ttk.Label(svc, text="", style="Muted.TLabel")
        self.lbl_host_warn.pack(fill="x", padx=28)
        self.var_host.trace_add("write", lambda *a: self._host_warn())
        self._row(svc, "端口", ttk.Entry(svc, textvariable=self.var_port), hint="【需重启】默认 8000")

        # 大模型
        llm = self._card(outer, "大模型（OpenAI 兼容）")
        llm.pack(fill="x", pady=6)
        self.var_provider = tk.StringVar()
        self.var_base = tk.StringVar()
        self.var_model = tk.StringVar()
        self.var_vmodel = tk.StringVar()
        self.var_key = tk.StringVar()
        self._row(llm, "Provider", ttk.Entry(llm, textvariable=self.var_provider),
                  hint="local / ollama / cloud（仅标识）【需重启】")
        self._row(llm, "base_url", ttk.Entry(llm, textvariable=self.var_base),
                  hint="本地 http://127.0.0.1:11434/v1 ；云端填对应地址【需重启】")
        self._row(llm, "文本模型", ttk.Entry(llm, textvariable=self.var_model))
        self._row(llm, "视觉模型", ttk.Entry(llm, textvariable=self.var_vmodel))
        self._row(llm, "API Key", ttk.Entry(llm, textvariable=self.var_key, show="•"),
                  hint="云端填真实 key；本地随便填【需重启】")

        # 行为
        beh = self._card(outer, "答题行为")
        beh.pack(fill="x", pady=6)
        self.var_trust = tk.StringVar()
        trust_cb = ttk.Combobox(beh, textvariable=self.var_trust, state="readonly",
                                values=[t[0] for t in TRUST_OPTIONS])
        self._row(beh, "信任策略", trust_cb, hint="三级：OCS请求参数 > 此处 > .env默认")
        self.var_llm = tk.BooleanVar()
        self.var_vision = tk.BooleanVar()
        self.var_sim = tk.StringVar()
        row2 = ttk.Frame(beh)
        row2.pack(fill="x", padx=14, pady=6)
        ttk.Label(row2, text="开关", width=14).pack(side="left")
        ttk.Checkbutton(row2, text="启用大模型", variable=self.var_llm).pack(side="left", padx=6)
        ttk.Checkbutton(row2, text="启用识图", variable=self.var_vision).pack(side="left", padx=6)
        self._row(beh, "相似阈值", ttk.Entry(beh, textvariable=self.var_sim), hint="0-1，默认 0.75")

        # 底部按钮
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", pady=12, padx=14)
        self.lbl_status = tk.Label(btns, text="", bg=C_BG, fg=C_MUTED, font=("Microsoft YaHei", 9))
        self.lbl_status.pack(side="left")
        ttk.Button(btns, text="保存", style="Accent.TButton", command=self._save).pack(side="right", padx=4)
        ttk.Button(btns, text="关闭", style="Ghost.TButton", command=self._close).pack(side="right")

    def _host_warn(self):
        if self.var_host.get().strip() == "0.0.0.0":
            self.lbl_host_warn.configure(text="⚠ 0.0.0.0 将把服务暴露到局域网，请确认已加鉴权/防火墙",
                                         foreground=C_RED)
        else:
            self.lbl_host_warn.configure(text="仅本机可访问（推荐）", foreground=C_MUTED)

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 载入/保存 ----------
    def _load(self):
        env = sc.ensure_env()
        self.var_host.set(env.get("HOST", "127.0.0.1"))
        self.var_port.set(env.get("PORT", "8000"))
        self.var_provider.set(env.get("LLM_PROVIDER", "ollama"))
        self.var_base.set(env.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1"))
        self.var_model.set(env.get("LLM_MODEL", "qwen2.5:7b"))
        self.var_vmodel.set(env.get("VISION_MODEL", "qwen2.5vl:7b"))
        self.var_key.set(env.get("LLM_API_KEY", ""))
        self.var_sim.set(env.get("SIMILARITY_THRESHOLD", "0.75"))
        self.var_trust.set(env.get("DEFAULT_ANSWER_TRUST", "prefer_trusted"))
        self.var_llm.set(env.get("ENABLE_LLM", "true").lower() == "true")
        self.var_vision.set(env.get("ENABLE_VISION", "true").lower() == "true")
        self._host_warn()

    def _save(self):
        port = self.var_port.get().strip()
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            messagebox.showerror("错误", "端口必须是 1-65535 的数字")
            return
        try:
            sim = float(self.var_sim.get())
            if not (0 <= sim <= 1):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "相似阈值必须是 0-1 之间的小数")
            return

        updates = {
            "HOST": self.var_host.get().strip() or "127.0.0.1",
            "PORT": port,
            "LLM_PROVIDER": self.var_provider.get().strip() or "ollama",
            "LLM_BASE_URL": self.var_base.get().strip(),
            "LLM_MODEL": self.var_model.get().strip(),
            "VISION_MODEL": self.var_vmodel.get().strip(),
            "LLM_API_KEY": self.var_key.get(),
            "SIMILARITY_THRESHOLD": self.var_sim.get().strip(),
            "DEFAULT_ANSWER_TRUST": self.var_trust.get() or "prefer_trusted",
            "ENABLE_LLM": "true" if self.var_llm.get() else "false",
            "ENABLE_VISION": "true" if self.var_vision.get() else "false",
        }
        try:
            sc.update_env(updates)
        except Exception as e:
            messagebox.showerror("保存失败", f"写入 .env 失败: {e}")
            return

        # 尝试热更新到运行中的后端（信任策略/开关/模型可即时生效）
        hot = self._push_hot(updates)
        msg = "已保存到 .env。"
        if hot:
            msg += " 部分设置已热更新到运行中的服务。"
        msg += "\n（监听地址/端口/模型/Key 变更需重启服务生效）"
        self.lbl_status.configure(text="✓ 已保存", fg=C_GREEN)
        self.root.after(2500, lambda: self.lbl_status.configure(text=""))
        messagebox.showinfo("已保存", msg)

    def _push_hot(self, updates: dict) -> bool:
        """把运行期可热更新的项推给后端 settings API。"""
        if not sc.is_backend_alive():
            return False
        token = sc.admin_token()
        body = {
            "default_answer_trust": updates["DEFAULT_ANSWER_TRUST"],
            "enable_llm": updates["ENABLE_LLM"],
            "enable_vision": updates["ENABLE_VISION"],
            "llm_model": updates["LLM_MODEL"],
            "vision_model": updates["VISION_MODEL"],
        }
        try:
            port = sc.env_port()
            url = f"http://{sc.probe_host()}:{port}/api/admin/settings"
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(), method="PUT",
                headers={"Content-Type": "application/json", "X-Admin-Token": token},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

    def _close(self):
        if self._own_root:
            self.root.destroy()
        else:
            self.root.withdraw()


def open_config(root: tk.Tk | None = None):
    """供托盘调用：打开配置窗口（复用托盘主 Tk root，用 Toplevel）。"""
    if root is None:
        ConfigWindow()
        return
    win = tk.Toplevel(root)
    ConfigWindow(root=win)


if __name__ == "__main__":
    ConfigWindow()
