"""托盘自带配置界面（tkinter/ttk，Grid 对齐布局）。

功能（0.2.0）：
- 提供商配置档案：下拉切换、新建/保存/删除/设为生效（走后端 /api/admin/llm/profiles）
- 获取模型列表、测试连接（走后端 /api/admin/llm/models、/llm/test）
- 答题行为：信任策略、开关、相似阈值（写 .env + 热更新后端 settings）

设计：以"档案"为中心的 LLM 配置；基础项（端口/监听）仍写 .env。
后端未运行时，档案/模型/测试等能力提示先启动后端。
"""
from __future__ import annotations

import json
import tkinter as tk
import urllib.request
from tkinter import messagebox, ttk

from scripts import service_control as sc

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


def _api(method: str, path: str, body: dict | None = None, timeout: float = 35) -> dict:
    """调用后端管理 API（带 token）。"""
    port = sc.env_port()
    url = f"http://{sc.probe_host()}:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", "X-Admin-Token": sc.admin_token(),
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


class ConfigWindow:
    def __init__(self, root: tk.Tk | None = None):
        self._owns_root = root is None
        self.root = root or tk.Tk()
        self.root.title("OCS 题库助手 · 配置")
        self.root.configure(bg=C_BG)
        self.root.resizable(True, True)
        self.root.minsize(620, 680)
        self.profiles: list[dict] = []
        self._style()
        self._build()
        self._load_base()
        self._load_profiles()
        self._center(640, 740)
        if self._owns_root:
            self.root.mainloop()

    # ---------- 样式 ----------
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Card.TLabelframe", background=C_PANEL, bordercolor=C_PANEL2, relief="solid", borderwidth=1)
        st.configure("Card.TLabelframe.Label", background=C_PANEL, foreground=C_ACCENT, font=("Microsoft YaHei", 10, "bold"))
        st.configure("TLabel", background=C_PANEL, foreground=C_TEXT, font=("Microsoft YaHei", 9))
        st.configure("Muted.TLabel", background=C_PANEL, foreground=C_MUTED, font=("Microsoft YaHei", 8))
        st.configure("TEntry", fieldbackground=C_PANEL2, foreground=C_TEXT, insertcolor=C_TEXT)
        st.configure("TCombobox", fieldbackground=C_PANEL2, foreground=C_TEXT)
        st.configure("Accent.TButton", background=C_ACCENT, foreground="#fff", font=("Microsoft YaHei", 9, "bold"), borderwidth=0, padding=6)
        st.map("Accent.TButton", background=[("active", "#3f78e0")])
        st.configure("Ghost.TButton", background=C_PANEL2, foreground=C_TEXT, font=("Microsoft YaHei", 9), borderwidth=0, padding=5)
        st.configure("Green.TButton", background=C_GREEN, foreground="#fff", font=("Microsoft YaHei", 9, "bold"), borderwidth=0, padding=5)
        st.configure("Red.TButton", background=C_RED, foreground="#fff", font=("Microsoft YaHei", 9), borderwidth=0, padding=5)

    def _card(self, parent, title):
        return ttk.LabelFrame(parent, text="  " + title + "  ", style="Card.TLabelframe")

    def _grid_row(self, parent, row, label, widget, hint=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=(12, 8), pady=5)
        widget.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=5)
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").grid(
                row=row + 1, column=1, sticky="w", padx=(0, 12), pady=(0, 2)
            )
            return row + 2
        return row + 1

    def _build(self):
        ttk.Label(self.root, text="⚙  OCS 题库助手配置", background=C_BG, foreground=C_TEXT,
                  font=("Microsoft YaHei", 13, "bold")).pack(pady=(12, 2))
        ttk.Label(self.root, text="提供商档案可在下拉切换；改端口/监听后需重启服务",
                  background=C_BG, foreground=C_MUTED, font=("Microsoft YaHei", 8)).pack()

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=12, pady=10)

        # ---- 服务 ----
        svc = self._card(outer, "服务")
        svc.pack(fill="x", pady=6)
        svc.columnconfigure(1, weight=1)
        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar()
        r = 0
        r = self._grid_row(svc, r, "监听地址", ttk.Combobox(svc, textvariable=self.var_host, values=["127.0.0.1", "0.0.0.0"]))
        r = self._grid_row(svc, r, "端口", ttk.Entry(svc, textvariable=self.var_port), hint="默认 8000，改后【需重启】")

        # ---- 提供商档案 ----
        pf = self._card(outer, "提供商配置档案")
        pf.pack(fill="x", pady=6)
        pf.columnconfigure(1, weight=1)
        r = 0
        self.var_profile = tk.StringVar()
        self.cb_profile = ttk.Combobox(pf, textvariable=self.var_profile, state="readonly")
        self.cb_profile.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=5)
        self.cb_profile.bind("<<ComboboxSelected>>", lambda e: self._on_profile_select())
        r += 1
        btnrow = ttk.Frame(pf)
        btnrow.grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
        ttk.Button(btnrow, text="设为生效", style="Green.TButton", command=self._activate_profile).pack(side="left", padx=3)
        ttk.Button(btnrow, text="新建", style="Ghost.TButton", command=self._new_profile).pack(side="left", padx=3)
        ttk.Button(btnrow, text="删除", style="Red.TButton", command=self._delete_profile).pack(side="left", padx=3)
        ttk.Button(btnrow, text="测试连接", style="Ghost.TButton", command=self._test_conn).pack(side="left", padx=3)
        r += 1

        self.var_name = tk.StringVar()
        self.var_provider = tk.StringVar()
        self.var_base = tk.StringVar()
        self.var_model = tk.StringVar()
        self.var_vision = tk.StringVar()
        self.var_key = tk.StringVar()
        r = self._grid_row(pf, r, "名称", ttk.Entry(pf, textvariable=self.var_name))
        r = self._grid_row(pf, r, "Provider", ttk.Entry(pf, textvariable=self.var_provider))
        r = self._grid_row(pf, r, "base_url", ttk.Entry(pf, textvariable=self.var_base))
        # 模型行 + 获取模型
        ttk.Label(pf, text="文本模型").grid(row=r, column=0, sticky="e", padx=(12, 8), pady=5)
        mrow = ttk.Frame(pf)
        mrow.grid(row=r, column=1, sticky="ew", padx=(0, 12), pady=5)
        mrow.columnconfigure(0, weight=1)
        ttk.Entry(mrow, textvariable=self.var_model).grid(row=0, column=0, sticky="ew")
        ttk.Button(mrow, text="获取模型", style="Ghost.TButton", command=self._fetch_models).grid(row=0, column=1, padx=(6, 0))
        self.cb_models = ttk.Combobox(mrow, state="readonly", width=16)
        self.cb_models.grid(row=0, column=2, padx=(6, 0))
        self.cb_models.bind("<<ComboboxSelected>>", lambda e: self._pick_model())
        r += 1
        r = self._grid_row(pf, r, "视觉模型", ttk.Entry(pf, textvariable=self.var_vision))
        # API Key
        ttk.Label(pf, text="API Key").grid(row=r, column=0, sticky="e", padx=(12, 8), pady=5)
        krow = ttk.Frame(pf)
        krow.grid(row=r, column=1, sticky="ew", padx=(0, 12), pady=5)
        krow.columnconfigure(0, weight=1)
        ttk.Entry(krow, textvariable=self.var_key, show="•").grid(row=0, column=0, sticky="ew")
        r += 1
        self.lbl_pf_msg = tk.Label(pf, text="", bg=C_PANEL, fg=C_MUTED, font=("Microsoft YaHei", 8), anchor="w")
        self.lbl_pf_msg.grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 4))
        r += 1
        ttk.Button(pf, text="保存档案", style="Accent.TButton", command=self._save_profile).grid(
            row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        # ---- 答题行为 ----
        beh = self._card(outer, "答题行为")
        beh.pack(fill="x", pady=6)
        beh.columnconfigure(1, weight=1)
        r = 0
        self.var_trust = tk.StringVar()
        r = self._grid_row(beh, r, "信任策略", ttk.Combobox(beh, textvariable=self.var_trust, state="readonly",
                                                            values=[t[0] for t in TRUST_OPTIONS]),
                           hint="三级：OCS请求 > 档案/设置 > .env")
        self.var_llm = tk.BooleanVar()
        self.var_vision = tk.BooleanVar()
        ttk.Label(beh, text="开关").grid(row=r, column=0, sticky="e", padx=(12, 8), pady=5)
        chk = ttk.Frame(beh)
        chk.grid(row=r, column=1, sticky="w", padx=(0, 12), pady=5)
        ttk.Checkbutton(chk, text="启用大模型", variable=self.var_llm).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(chk, text="启用识图", variable=self.var_vision).pack(side="left")
        r += 1
        self.var_sim = tk.StringVar()
        r = self._grid_row(beh, r, "相似阈值", ttk.Entry(beh, textvariable=self.var_sim), hint="0-1，默认 0.75")

        # ---- 底部 ----
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=12, pady=(4, 12))
        self.lbl_status = tk.Label(bottom, text="", bg=C_BG, fg=C_MUTED, font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="保存基础设置", style="Accent.TButton", command=self._save_base).pack(side="right", padx=4)
        ttk.Button(bottom, text="关闭", style="Ghost.TButton", command=self._close).pack(side="right")

    def _center(self, w, h):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")

    # ---------- 基础项 ----------
    def _load_base(self):
        env = sc.ensure_env()
        self.var_host.set(env.get("HOST", "127.0.0.1"))
        self.var_port.set(env.get("PORT", "8000"))
        self.var_sim.set(env.get("SIMILARITY_THRESHOLD", "0.75"))
        self.var_trust.set(env.get("DEFAULT_ANSWER_TRUST", "prefer_trusted"))
        self.var_llm.set(env.get("ENABLE_LLM", "true").lower() == "true")
        self.var_vision.set(env.get("ENABLE_VISION", "true").lower() == "true")

    def _save_base(self):
        port = self.var_port.get().strip()
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            messagebox.showerror("错误", "端口必须是 1-65535 的数字"); return
        try:
            sim = float(self.var_sim.get())
            if not (0 <= sim <= 1):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "相似阈值必须是 0-1 的小数"); return
        updates = {
            "HOST": self.var_host.get().strip() or "127.0.0.1",
            "PORT": port,
            "SIMILARITY_THRESHOLD": self.var_sim.get().strip(),
            "DEFAULT_ANSWER_TRUST": self.var_trust.get() or "prefer_trusted",
            "ENABLE_LLM": "true" if self.var_llm.get() else "false",
            "ENABLE_VISION": "true" if self.var_vision.get() else "false",
        }
        try:
            sc.update_env(updates)
        except Exception as e:
            messagebox.showerror("保存失败", f"写入 .env 失败: {e}"); return
        hot = self._push_hot(updates)
        self._status("✓ 基础设置已保存" + ("（部分热更新）" if hot else "") + "；端口/监听变更需重启")
        messagebox.showinfo("已保存", "基础设置已保存。端口/监听变更需重启服务生效。")

    def _push_hot(self, updates: dict) -> bool:
        if not sc.is_backend_alive():
            return False
        try:
            _api("PUT", "/api/admin/settings", {
                "default_answer_trust": updates["DEFAULT_ANSWER_TRUST"],
                "enable_llm": updates["ENABLE_LLM"],
                "enable_vision": updates["ENABLE_VISION"],
            })
            return True
        except Exception:
            return False

    # ---------- 档案 ----------
    def _backend_ready(self) -> bool:
        if not sc.is_backend_alive():
            messagebox.showwarning("后端未运行", "提供商档案需要后端服务运行。请先在托盘右键「启动服务」。")
            return False
        return True

    def _load_profiles(self):
        try:
            self.profiles = _api("GET", "/api/admin/llm/profiles").get("items", [])
        except Exception:
            self.profiles = []
            self._pf_msg("未连接后端，档案功能不可用", err=True)
        names = [p["name"] + (" ✓生效" if p.get("is_active") else "") for p in self.profiles]
        self.cb_profile["values"] = names if names else ["(无档案)"]
        act = next((p for p in self.profiles if p.get("is_active")), None)
        if act:
            self.var_profile.set(act["name"] + " ✓生效"); self._fill_profile(act)
        elif self.profiles:
            self.var_profile.set(names[0]); self._fill_profile(self.profiles[0])
        else:
            self.var_profile.set("(无档案)")

    def _on_profile_select(self):
        val = self.var_profile.get().replace(" ✓生效", "")
        p = next((x for x in self.profiles if x["name"] == val), None)
        if p:
            self._fill_profile(p)

    def _fill_profile(self, p: dict):
        self.var_name.set(p.get("name", ""))
        self.var_provider.set(p.get("provider", ""))
        self.var_base.set(p.get("base_url", ""))
        self.var_model.set(p.get("model", ""))
        self.var_vision.set(p.get("vision_model", ""))
        self.var_key.set("")
        self._pf_msg("已设置（留空=不修改）" if p.get("api_key_set") else "填 API Key")

    def _new_profile(self):
        for v in (self.var_name, self.var_provider, self.var_base, self.var_model, self.var_vision, self.var_key):
            v.set("")
        self.var_profile.set("")
        self._pf_msg("新建：填写后点『保存档案』")

    def _current_profile(self):
        val = self.var_profile.get().replace(" ✓生效", "")
        return next((x for x in self.profiles if x["name"] == val), None)

    def _form_body(self) -> dict:
        b = {
            "name": self.var_name.get().strip(),
            "provider": self.var_provider.get().strip() or "custom",
            "base_url": self.var_base.get().strip(),
            "model": self.var_model.get().strip(),
            "vision_model": self.var_vision.get().strip(),
        }
        if self.var_key.get():
            b["api_key"] = self.var_key.get()
        return b

    def _save_profile(self):
        if not self._backend_ready():
            return
        body = self._form_body()
        if not body["name"]:
            messagebox.showerror("错误", "请填写档案名称"); return
        cur = self._current_profile()
        try:
            if cur:
                _api("PUT", f"/api/admin/llm/profiles/{cur['id']}", body)
            else:
                body["activate"] = True
                _api("POST", "/api/admin/llm/profiles", body)
            self._pf_msg("✓ 档案已保存")
            self._load_profiles()
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _delete_profile(self):
        if not self._backend_ready():
            return
        cur = self._current_profile()
        if not cur:
            messagebox.showwarning("提示", "请先选择一个档案"); return
        if not messagebox.askyesno("确认", f"删除档案「{cur['name']}」？"):
            return
        try:
            _api("DELETE", f"/api/admin/llm/profiles/{cur['id']}")
            self._load_profiles(); self._pf_msg("已删除")
        except Exception as e:
            messagebox.showerror("删除失败", str(e))

    def _activate_profile(self):
        if not self._backend_ready():
            return
        cur = self._current_profile()
        if not cur:
            messagebox.showwarning("提示", "请先选择一个档案"); return
        try:
            _api("POST", f"/api/admin/llm/profiles/{cur['id']}/activate")
            self._load_profiles(); self._pf_msg("✓ 已设为生效")
        except Exception as e:
            messagebox.showerror("操作失败", str(e))

    def _fetch_models(self):
        if not self._backend_ready():
            return
        self._pf_msg("获取模型中…")
        try:
            base = self.var_base.get().strip()
            key = self.var_key.get()
            q = []
            if base:
                q.append("base_url=" + urllib.request.quote(base))
            if key:
                q.append("api_key=" + urllib.request.quote(key))
            path = "/api/admin/llm/models" + ("?" + "&".join(q) if q else "")
            r = _api("GET", path)
            if not r.get("ok"):
                self._pf_msg("获取失败：" + (r.get("error") or ""), err=True); return
            models = r.get("models") or []
            self.cb_models["values"] = models
            self._pf_msg(f"共 {len(models)} 个模型，右侧下拉选择")
        except Exception as e:
            self._pf_msg("获取失败：" + str(e), err=True)

    def _pick_model(self):
        m = self.cb_models.get()
        if m:
            self.var_model.set(m)

    def _test_conn(self):
        if not self._backend_ready():
            return
        self._pf_msg("测试连接中…")
        body = {"base_url": self.var_base.get().strip(), "model": self.var_model.get().strip()}
        if self.var_key.get():
            body["api_key"] = self.var_key.get()
        try:
            r = _api("POST", "/api/admin/llm/test", body)
            if r.get("ok"):
                self._pf_msg(f"✓ 连接成功 · {r.get('model')} · {r.get('latency_ms')}ms")
            else:
                self._pf_msg("连接失败：" + (r.get("error") or ""), err=True)
        except Exception as e:
            self._pf_msg("测试失败：" + str(e), err=True)

    def _pf_msg(self, text, err=False):
        self.lbl_pf_msg.configure(text=text, fg=(C_RED if err else C_GREEN))

    def _status(self, text):
        self.lbl_status.configure(text=text, fg=C_GREEN)
        self.root.after(3500, lambda: self.lbl_status.configure(text=""))

    def _close(self):
        if self._owns_root:
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
