# 开发日志（Development Log）

> 项目：OCS 自建题库后端 + 托盘管理系统
> 版本：v0.1.0
> 本文记录从零到 0.1.0 的开发历程：需求、关键决策、实现要点、踩坑与当前状态。

---

## 阶段总览

| 阶段 | 内容 | 结果 |
|---|---|---|
| P0 | 研究 ocsjs 源码（题库配置/AnswererWrapper/答案匹配） | 完成源码研究笔记 |
| P1 | 设计自建题库后端（适配/存储/大模型/记录四层） | 完成架构设计 |
| P2 | 实现 Python+FastAPI 后端 | 26 项测试全绿 |
| P3 | 实现零构建 Web 管理台（Dashboard/题库/日志/设置） | 可用 |
| P4 | 桌面形态选型（命令行→托盘，多轮澄清） | 确定 Windows 系统托盘 |
| P5 | 托盘实现（Win32 消息循环 + 原生菜单） | 修复崩溃后可稳定运行 |
| P6 | 架构收敛：supervisor 作为后端唯一管理者 | 托盘/网页统一经 supervisor |
| P7 | 修复配置保存不生效 + 补 API Key | 配置真正生效 |
| P8 | 发布 0.1.0（git + GitHub 私密仓库 + 文档） | 本版本 |

---

## P0 研究 ocsjs 源码

- 获取 ocsjs 源码：GitHub 域名被本机 hosts 劫持到 127.0.0.1、schannel TLS 故障；改用 **Node 内置 https 经 ghproxy 镜像**下载仓库 zip；用户后续提供 5.2.7 源码包替换。
- 关键发现（详见 `ocsjs-study/NOTES-自动答题源码研究.md`）：
  - `defaultAnswerWrapperHandler(wrappers, env)` 参数顺序（文档写反）。
  - `handler` 是字符串，`Function(handler)()` 求值返回函数；多选答案用 `#` 拼接。
  - 答案匹配层 `worker/resolvers/*` + `splitAnswer`（分隔符含 `#`），程序题特判。
  - v5.2.7 起**禁止从 URL 加载题库配置**；已实现图片题优化判定（需 post + `${images}`）。

## P1 架构设计

四层 + 横切：① 适配层 ② 题库存储 ③ 大模型（文本+识图，本地/云端切换）④ 记录层。
关键决策：
- **题库唯一键 `qkey = hash(归一化题干 + 归一化选项排序 + 题型)`** → 同题干不同选项是不同题，各自独立答案。
- **两层记录**：request_logs（请求级）+ request_steps（步骤级，可回放）。
- **答案信任策略**：trusted/candidate/conflict，默认 prefer_trusted，三级覆盖。

## P2 后端实现

- 技术栈：Python 3.11 + FastAPI + SQLite（WAL）+ openai SDK（OpenAI 兼容）。
- 模块：adapter / admin / store / llm / pipeline / logging_store。
- 环境限制：本机无法 pip 安装 pytest（PyPI HTTPS 超时），改用**标准库 unittest** 写零依赖测试运行器 `tests/run_tests.py`（26 项）。
- 验证：命中/未命中/四题型/同题不同选项/含图识图/两层记录/候选转正/冲突/鉴权 均通过。

## P3 Web 管理台

- 零构建原生 HTML/JS（规避 npm 依赖与网络）。
- 页面：Dashboard（状态卡+SVG 趋势）、题库管理、日志（含步骤回放）、设置。
- 启动 `serve_admin.py` 独立托管静态文件，与后端解耦。

## P4 桌面形态选型（多轮澄清）

用户诉求演进：命令行 → 双击 bat/vbs → 纯网页 → 非网页桌面形态 → 最终**系统托盘程序**。
网络限制使"打包 exe"(PyInstaller 需联网) 不可行；选定**纯标准库托盘**（tkinter + ctypes）。

## P5 托盘实现与崩溃修复（重要踩坑）

- 首版「隐藏 Tk 窗口 + ctypes 子类化 WndProc」→ 真机**右键无反应 + 自动退出**。
- 根因：**ctypes 未声明 Win32 函数参数类型**，64 位指针被截断 → 每次窗口消息回调抛 `OverflowError/access violation` → 消息循环崩溃、进程退出。
- 修复：重写为**纯 Win32 消息循环**（自建隐藏窗口 + GetMessage/DispatchMessage + 原生 TrackPopupMenu），并**为所有 user32/kernel32/shell32 函数声明 argtypes/restype（64 位正确）**。
- 结果：前台 20–30s 稳定、stderr 全空；真机托盘图标出现、右键菜单与各命令正常（日志可见 WM_RBUTTONUP→显示菜单→命令分发）。

## P6 架构收敛：supervisor 唯一管理者

- 问题：托盘自己 Popen 管后端，网页按钮又要 supervisor 管后端 → 双头管理隐患。
- 决策（用户选 A）：**supervisor 成为后端唯一管理者**；托盘与网页都经 supervisor 启停。
- 改动：supervisor 加 `/ping`、`/shutdown`、按端口兜底强杀；service_control 加 supervisor 客户端；托盘启停改调 supervisor、退出连带关闭。
- 验证（独立端口 8011，避开本机无法杀的残留 8000）：启动/状态/重启/停止/关闭全通过。

## P7 配置生效修复 + API Key

- 发现深层 bug：网页/托盘保存的 base_url/model/api_key 只写 settings_kv，但后端 `client.py` 只读 `.env` → **保存不生效**。
- 修复：新增 `effective_llm()`（settings_kv 优先 > .env），client 改用它；GET settings 不回显 key 明文，只报 `llm_api_key_set`；网页设置页补 API Key 字段（密码框+显隐+留空不改）。

## P8 发布 0.1.0

- 版本统一为 0.1.0。
- 补齐文档：KNOWN_ISSUES / ARCHITECTURE / OCS_INTEGRATION / DEVELOPMENT_LOG / CHAT_TRANSCRIPT / README / CHANGELOG / LICENSE。
- Git 初始化，上传 GitHub 私密仓库。
- 已知问题（T1-T5/W1-W5/L1/D1/E1/O1）记录方案，计划 0.2.0 实现。

---

## 当前状态（0.1.0）

**已完成并可用**
- 后端 `/search`（GET/POST）+ OCS 契约返回；题库命中/大模型（文本+识图）/两层记录/信任策略/候选转正。
- 26 项零依赖测试全绿。
- Web 管理台（Dashboard/题库/日志/设置）。
- 系统托盘（Win32，启停+配置界面+打开管理台+日志）。
- supervisor 作为后端唯一管理者。

**已知待办**：见 `KNOWN_ISSUES.md`（0.2.0）。

## 技术踩坑清单（复盘）
1. ctypes 调 Win32 必须声明 argtypes/restype，否则 64 位指针截断崩溃（托盘核心 bug）。
2. 本 harness 命令结束会回收子进程树；托盘需真机 explorer 启动才能常驻。
3. `Get-NetTCPConnection` 在本环境不可靠，须用 `netstat -ano` 判断端口。
4. 跨会话孤儿进程本会话无权杀（Access denied），影响测试端口选择。
5. 配置保存必须让后端真正读取（effective_llm），否则"存了不生效"。
