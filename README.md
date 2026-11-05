# OCS 自建题库后端系统

![version](https://img.shields.io/badge/version-0.2.0-blue) ![python](https://img.shields.io/badge/python-3.11+-green) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

面向 OCS 网课助手的**自建题库后端**：OCS 发来题目 → 先查题库 → 未命中调大模型（文本/识图）作答 → **每道题都入库** → **每步操作都记录** → 按 OCS `AnswererWrapper` 契约返回答案。附带**独立 Web 管理台**（Dashboard / 题库 / 日志 / 设置 / 服务启停）与 **Windows 系统托盘程序**（本机启停 + 配置）。

技术栈：Python 3.11 + FastAPI + SQLite；前端零构建原生 HTML/JS；托盘纯标准库。

> 当前版本 **v0.2.0**。已知问题与路线图见 [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)，变更见 [CHANGELOG.md](CHANGELOG.md)。

## 文档索引
- [架构说明](docs/ARCHITECTURE.md) · [OCS 接入指南](docs/OCS_INTEGRATION.md)
- [已知问题与路线图](docs/KNOWN_ISSUES.md) · [开发日志](docs/DEVELOPMENT_LOG.md) · [对话记录](docs/CHAT_TRANSCRIPT.md)
- [变更日志](CHANGELOG.md)

---

## 架构（进程解耦）

```
① ocs-qa-server  FastAPI 后端：适配层 + 题库 + 大模型 + 记录 + 管理API
② ocs-admin-ui   独立静态前端：Dashboard/题库/日志/设置/启停
③ supervisor.py  独立进程：后端(①)的唯一管理者（启停/重启/健康）
④ 托盘程序       本机控制台：拉起③、经③启停①、起②、打开管理台、配置
        OCS ──HTTP──▶ ①/search     托盘 ──▶ ③(启停①) / ②(前端) / ①配置
                                     网页 ──▶ ③(启停) & ①(数据/设置)
```

- ① 不含任何 UI 代码；② 只通过 HTTP 调 ① 的管理 API，停掉不影响 `/search`。
- ③ 是后端 ① 的**唯一管理者**；托盘与网页都通过它启停后端，避免双头冲突。
- ④ 托盘只管"启动 ③、起 ②、开面板"，进程生命周期收口在 ③。

## 快速开始

### 方式 A：托盘程序（推荐，无需命令行）

双击项目根目录的 **`托盘控制.pyw`**（或英文名 `tray.pyw`）：
- 右下角出现托盘图标，无任何命令行窗口。
- **右键菜单**：状态（● 运行中 / ○ 已停止）、▶ 启动服务、■ 停止服务、↻ 重启服务、⚙ 配置…、🌐 打开管理台、📄 查看日志、退出。
- **⚙ 配置…**：图形化设置端口、监听地址、大模型(base_url/模型/Key)、信任策略、开关；安全项写回 `.env`，可热更新项即时同步到运行中的后端。
- 首次双击会自动从 `.env.example` 生成 `.env`。
- 重复双击不会开第二个实例（自动识别已在运行）。
- 退出时若后端/supervisor 仍在运行，会询问是否一并停止。

> **架构说明**：托盘启停后端时，实际是**拉起 supervisor 并调用它的接口**（统一由 supervisor 管理后端），
> 因此托盘和网页管理台的「服务启停」都走同一套 supervisor，不会冲突。日常只用托盘一个入口即可。

> 想开机自启：`Win+R` 输入 `shell:startup`，把 `托盘控制.pyw` 的快捷方式放进去即可。

### 方式 B：命令行（备选）

```powershell
cd ocs-qa-server
Copy-Item .env.example .env      # 按需修改
python -m pip install -r requirements.txt   # 若依赖未装

# 1) 灌示例题库（可选）
python -m scripts.seed

# 2) 启动后端
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3) 启动管理台前端（另开终端）
python -m scripts.serve_admin --port 8020
# 浏览器打开 http://127.0.0.1:8020/

# 4) 启动 supervisor 以支持“服务启停”按钮（另开终端）
python -m scripts.supervisor --port 8010 --backend-port 8000
```

> 也可用 `python scripts/run_all.py` 一键起三进程（见下）。

API 文档：<http://127.0.0.1:8000/docs>

## 接入 OCS

生成题库配置 JSON：

```powershell
python -m scripts.export_ocs_config --host 192.168.1.10 --port 8000 --trust prefer_trusted
```

把输出（也写入 `ocs_config.generated.json`）整段粘贴到 OCS 的「题库配置」框。示例：

```json
[{
  "name": "自建题库",
  "homepage": "http://192.168.1.10:8000",
  "url": "http://192.168.1.10:8000/search",
  "method": "get",
  "responseType": "json",
  "data": { "title": "${title}", "type": "${type}", "options": "${options}", "answer_trust": "prefer_trusted" },
  "handler": "return (res)=> (res && res.code===1) ? [res.question, res.answer] : (res && res.msg ? [res.msg, undefined] : undefined)"
}]
```

**@connect**：OCS 脚本默认只允许白名单域名。请把题库域名加入脚本 `@connect`，或使用官方「全域名通用版」；本地调试用 `127.0.0.1` 需脚本允许。注意 **OCS v5.2.7 起不再支持从 URL 加载题库配置**，必须粘贴上面的 JSON。

## 大模型：本地 / 云端切换

统一走 **OpenAI 兼容协议**，改 `.env`（或在管理台「设置」页）即可：

| 场景 | LLM_BASE_URL | LLM_MODEL | VISION_MODEL |
|---|---|---|---|
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` | `qwen2.5vl:7b` |
| 云端(OpenAI兼容) | 对应地址 | 对应模型 | 支持视觉的模型 |

`LLM_API_KEY` 本地随便填，云端填真实 key。

## 答案信任策略（三级覆盖）

`trusted_only` / `prefer_trusted`（默认）/ `allow_candidate`。优先级：**OCS 请求参数 `answer_trust` > 管理台设置 > `.env` 默认**。

- 大模型答案默认入为 **candidate（候选）**，不直接复用于后续命中（除非策略为 allow_candidate 或管理员转正）。
- 管理员可在管理台把候选「设为可信」，或用 `python -m scripts.verify_answers` 批量转正。

## 核心数据模型

- **题库唯一键 `qkey = hash(归一化题干 + 归一化选项排序 + 题型)`**。→ 题干相同但**选项不同 = 两条独立记录、各自独立答案**，不会串答案。
- `answers.status ∈ {trusted, candidate, conflict}`；冲突答案并存不覆盖。
- **两层记录**：`request_logs`（请求级概要，1 行/请求）+ `request_steps`（步骤级明细，每步一行，`stage ∈ receive/normalize/store_lookup/vision/llm_request/llm_response/parse/store_write/finalize`）。管理台可按 `request_id` 回放整条链路。

## 目录

```
ocs-qa-server/
├─ 托盘控制.pyw          ★ 双击启动托盘程序（无窗口），英文名 tray.pyw
├─ app/                 FastAPI 后端
│  ├─ main.py config.py pipeline.py logging_store.py
│  ├─ adapter/           /search /health（OCS 契约）
│  ├─ admin/             /api/admin/*（管理 API）
│  ├─ store/             SQLite + 仓储 + qkey
│  └─ llm/               client/answerer/vision
├─ ocs-admin-ui/        独立前端（零构建）
├─ scripts/             seed / verify_answers / export_ocs_config / supervisor / serve_admin / run_all / e2e_http_check
│  └─ tray.py / tray_config.py / tray_icons.py / service_control.py   托盘程序与配置界面
└─ tests/                run_tests.py（标准库 unittest，零依赖）+ pytest 版本
```

## 测试

本机网络受限无法 pip 安装 pytest，提供零依赖测试运行器：

```powershell
python tests/run_tests.py
```

覆盖：命中/未命中、GET/POST、中文/空格/#编码、四题型、多选 `#`、**同题不同选项各答各**、含图触发识图/无图不触发、识图降级、候选入库与转正、冲突标记、两层记录与回放、管理 API 鉴权/CRUD/设置。

有 pytest 的环境可直接 `pytest tests/`（`tests/conftest.py` 为 pytest 版 fixture）。

外部服务已起来时，可跑真实 HTTP 端到端：

```powershell
python scripts/e2e_http_check.py
```

## 配置项（.env）

见 `.env.example`。关键项：`HOST/PORT/ADMIN_TOKEN/DB_PATH/LLM_*/VISION_MODEL/DEFAULT_ANSWER_TRUST/ENABLE_LLM/ENABLE_VISION/SIMILARITY_THRESHOLD`。
