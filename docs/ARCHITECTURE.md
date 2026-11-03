# 架构说明（Architecture）

> 版本：v0.1.0

## 1. 总体架构：三进程 + 托盘解耦

```
             ┌────────────────────────────────────────────────────────┐
   OCS 脚本  │  (浏览器 / 油猴，发 GET/POST /search)                     │
   浏览器    └───────────────┬────────────────────────────────────────┘
                             │ HTTP
   ┌─────────────────────────▼───────────────────────────────────────┐
   │ ① ocs-qa-server  FastAPI 后端                                     │
   │   adapter(/search) → pipeline → store / llm / logging           │
   │   管理 API (/api/admin/*)                                        │
   └───────────▲──────────────────────────────┬──────────────────────┘
               │ HTTP                          │ 读 settings / 数据
   ┌───────────┴───────────┐      ┌────────────▼────────────────────┐
   │ ③ supervisor (8010)    │      │ ② ocs-admin-ui (8020 静态前端)   │
   │   后端 ① 的唯一管理者   │◀─────│   Dashboard/题库/日志/设置       │
   │   start/stop/restart   │ HTTP │   通过 ③ 启停、通过 ① 读数据      │
   └───────────▲───────────┘      └─────────────────────────────────┘
               │ HTTP
   ┌───────────┴────────────────────────────────────────────────────┐
   │ ④ 托盘程序 (Windows 系统托盘，纯标准库 tkinter+ctypes)            │
   │   拉起 ③、经 ③ 启停 ①、起 ②、打开管理台、配置界面              │
   └─────────────────────────────────────────────────────────────────┘
```

**职责划分**
- ① 后端：不含 UI；对外只暴露 `/search` 与 `/api/admin/*`。
- ② 前端：纯静态，零构建；只通过 HTTP 访问 ①（数据）与 ③（启停）。
- ③ supervisor：**后端进程的唯一管理者**，避免托盘与网页双头管理冲突。
- ④ 托盘：本机控制台入口；不直接托管后端（经 ③），负责拉起 ③、起 ②、开面板、配置。

## 2. 后端分层

```
app/
├─ main.py            FastAPI 装配、启动初始化 DB、CORS
├─ config.py          pydantic-settings（.env）；effective_llm() 合并运行期配置
├─ adapter/           OCS 契约入口 /search、/health
├─ admin/             管理 API /api/admin/*（题库/答案/日志/设置/dashboard）
├─ store/             SQLite：db.py(建表/WAL) repository.py(仓储) models.py
├─ llm/               client.py(OpenAI 兼容) answerer.py(文本) vision.py(识图)
├─ pipeline.py        编排：查库→(识图)→LLM→解析→入库→两层记录→返回
└─ logging_store.py   两层记录 request_logs + request_steps
```

### 请求编排（pipeline.handle_search）
`receive → normalize → store_lookup → (vision) → llm_request/response → parse → store_write → finalize`
- 命中 trusted（按信任策略）直接返回并记 hit。
- 未命中走大模型；LLM 答案入为 **candidate（候选）**，需转正才可信。
- 无论命中与否都按 `qkey` upsert 题库。

### 答案信任策略
`trusted_only / prefer_trusted(默认) / allow_candidate`；优先级：**OCS 请求参数 > 网页/托盘设置(settings_kv) > .env 默认**。

## 3. 数据模型（现状 v0.1.0）

```sql
questions(
  qkey TEXT PK,            -- hash(归一化题干 + 归一化选项排序 + 题型)
  question_raw TEXT, question_norm TEXT,
  type TEXT,               -- single/multiple/judgement/completion/unknown
  options_json TEXT,       -- JSON 数组
  created_at TEXT)

answers(
  id PK, qkey FK, answer TEXT,
  source TEXT,             -- store/llm/merged
  status TEXT,             -- trusted/candidate/conflict
  confidence REAL, hit_count INT,
  verified_at TEXT, candidates_json TEXT, created_at TEXT)

request_logs(...)          -- 请求级概要（1 行/请求）
request_steps(...)         -- 步骤级明细（每步一行：stage/input/output/latency/ok/error）
settings_kv(key PK, value) -- 运行期设置
```

**关键设计：`qkey = hash(归一化题干 + 归一化选项排序 + 题型)`**
→ 题干相同但**选项不同 = 两条独立记录、各自独立答案**，避免串答案。

## 4. 数据模型演进方案（面向扩展性，0.2.0 实施）

> 详见 `KNOWN_ISSUES.md` 的 D1。此处记录目标结构。

### 4.1 题型注册表
```sql
question_types(code PK, name TEXT, answer_schema TEXT, enabled INT)
-- 内置：single/multiple/judgement/completion/unknown
-- 新增题型（排序/匹配/编程…）只需插入一行 + 定义 answer_schema(JSON Schema)
```
`questions.type` 逻辑引用；读取时 JOIN 校验，未注册回退 `unknown`。

### 4.2 答案结构化
```sql
answers(
  ...,
  answer TEXT,             -- 保留：对外 OCS 文本渲染（多选 # 拼接、填空 # 拼接）
  answer_json TEXT         -- 新增：按题型存结构化答案
)
-- single/multiple: {"option_ids":["A","C"]}
-- judgement:       {"value": true}
-- completion:      {"blanks":["H2O"]}
```
对外仍由 `answer_json` 渲染成 OCS 需要的文本，保证兼容。

### 4.3 选项独立表
```sql
options(id PK, qkey FK, idx INT, content TEXT, is_image INT)
```
取代裸 `options_json`（`questions.options_json` 保留为快照兼容），便于统计、图片题、去重、排序题。

### 4.4 迁移与兼容
- 启动时检测旧库结构，自动把 `options_json` 迁入 `options` 表，答案文本回填 `answer_json`（按题型推断）。
- 读写经兼容层，旧数据无损可用。

## 5. 配置生效链（重要）

`effective_llm()`（`app/config.py`）合并顺序：
**当前激活的 provider profile（0.2.0）> settings_kv（网页/托盘保存）> .env > 代码默认**。

> 0.1.0 已实现 settings_kv 覆盖 .env（修复"保存不生效"）。provider profiles 于 0.2.0 引入。

## 6. 进程与端口

| 进程 | 端口 | 说明 |
|---|---|---|
| 后端 uvicorn | 8000（.env PORT） | `/search`、`/api/admin/*`、`/docs` |
| supervisor | 8010 | 后端启停/状态；`/ping`、`/shutdown` |
| 前端静态 | 8020 | `serve_admin.py` 托管 `ocs-admin-ui/` |

## 7. 稳定性要点
- 托盘 Win32 消息回调：所有 ctypes 函数声明 64 位 argtypes/restype（历史 bug 根因）。
- 后端启停：supervisor 用 Popen 句柄 + 按端口兜底强杀。
- SQLite：WAL 模式；连接线程本地。

## 8. 安全要点
- 管理 API 需 `X-Admin-Token`（`.env` ADMIN_TOKEN）。
- API Key 不回显明文（只报 `llm_api_key_set`）；`.env` 不入库。
- 默认监听 `127.0.0.1`；改 `0.0.0.0` 需评估暴露风险。
