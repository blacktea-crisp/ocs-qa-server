# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [0.2.1] - 2026-11-05

### Added
- **网页生成 OCS 配置**：设置页「获取 OCS 题库配置」面板，可选 v1/v2、填 host/port，一键生成并复制 JSON（后端 `GET /api/admin/ocs-config`）。
- **题库命中详情**：日志详情显示命中的题库答案（ID/内容/状态/来源/历史命中次数）——后端 `/logs/{id}` 新增 `hit_answer`。
- **视觉模型列表**：`/api/admin/llm/models` 返回 `vision_models`（按模型名规则过滤），网页/托盘可分别选用文本模型与视觉模型。

### Fixed
- **托盘「打开配置」报 `main thread is not in main loop`**：托盘为纯 Win32 消息循环、无 tkinter loop，配置界面改为**独立进程**启动；并修复配置窗口 `var_vision` 变量被 BooleanVar 覆盖导致的崩溃。
- **日志页无顶部栏、无日志**：`logs.html` 内联脚本存在多余 `}` 导致整页 JS 语法错误，已修复。
- **题库管理操作列错位**：操作按钮统一尺寸 + 禁止换行。
- **趋势图无时间轴**：请求趋势图增加时间轴基线与首/中/末时间刻度（viewBox 固定坐标，文字不变形）。
- **数据库启动偶发 `database is locked`**：连接加 `busy_timeout`；迁移用 `PRAGMA user_version` 标记版本，达标后跳过（减少启动写锁）。

## [0.2.0] - 2026-11-05

### Added
- **数据结构化（扩展性）**：
  - 新增 `question_types` 题型注册表（内置 single/multiple/judgement/completion/unknown，可扩展）。
  - `answers` 新增 `answer_json` 结构化答案（option_ids / bool / blanks / text）。
  - 新增 `options` 选项独立表（替代裸 options_json，保留快照兼容）。
  - 启动幂等迁移：自动回填 options 表、answer_json，旧数据无损。
- **提供商配置档案**：`llm_profiles` 表 + `/api/admin/llm/profiles` CRUD + activate；一套档案含全部 LLM 参数，可命名/编辑/删除/切换。生效优先级：激活档案 > 单项设置 > .env。
- **测试连接**：`POST /api/admin/llm/test`（发极简 chat 验证连通）。
- **获取模型列表**：`GET /api/admin/llm/models`（OpenAI 兼容 /models，失败可手填）。
- **导出数据**：`GET /api/admin/export`（csv/json/xlsx，可按题型/时间筛选、含候选）。
- **题库详情页**：`ocs-admin-ui/question.html?id=`，展示完整题干/选项/答案候选/相关日志，可在页内管理；列表截断统一补 `[…]`。
- **日志增强**：`/api/admin/logs` 支持按题目/仅错误/来源筛选；`/api/admin/logs/export`（csv/json）。
- **OCS 识图导出**：`export_ocs_config.py` 支持 v1/v2，**默认 v2**（post + ${images}/suggestion_*），解决「当前配置不支持识图」。

### Changed
- 网页 Dashboard 启停按钮整合为**单一两态按钮**（运行时红「停止」/停止时绿「启动」，重启降为次要）。
- 托盘配置界面改为 **Grid 对齐布局**（修复输入框错位），并集成提供商档案下拉、获取模型、测试连接。
- 设置页重构为「提供商配置档案」面板 + 答题设置。

### Fixed
- 托盘配置输入框错位。
- 网页设置保存的 LLM 配置不生效（`effective_llm` 统一合并，并支持激活档案）。

## [0.1.0] - 2026-11-03

首个公开版本。

### Added
- **后端（FastAPI + SQLite）**
  - OCS 题库适配接口 `GET/POST /search`，按 `AnswererWrapper` 契约返回。
  - 题库存储：`qkey = hash(归一化题干 + 归一化选项排序 + 题型)`，同题干不同选项独立作答。
  - 大模型答题（文本）与识图（多模态），OpenAI 兼容协议，本地/云端可切换。
  - 答案信任策略：`trusted_only / prefer_trusted / allow_candidate`，三级覆盖。
  - 候选答案机制：大模型答案入为 candidate，可转正/降级/标记冲突。
  - 两层记录：请求级 `request_logs` + 步骤级 `request_steps`（可按 request_id 回放）。
  - 管理 API `/api/admin/*`（题库、答案、日志、设置、dashboard）。
  - `effective_llm()`：运行期配置（保存的）优先于 `.env`。
- **Web 管理台**（零构建原生 HTML/JS）：Dashboard、题库管理、日志回放、设置（含 API Key）。
- **Windows 系统托盘**（纯标准库 tkinter+ctypes）：
  - 托盘图标 + 原生右键菜单（启动/停止/重启/配置/打开管理台/查看日志/退出）。
  - 配置界面；单实例；Win32 消息循环（已修复 ctypes 原型崩溃）。
- **supervisor**：后端进程的唯一管理者（启停/重启/状态，`/ping`、`/shutdown`）。
- **脚本**：`seed` 灌示例题库；`export_ocs_config` 导出 OCS 配置；`verify_answers` 候选转正；`serve_admin` 静态托管；`supervisor`；`run_all`；`e2e_http_check`。
- **测试**：零依赖 `tests/run_tests.py`（26 项）+ pytest 版。
- **文档**：README、ARCHITECTURE、OCS_INTEGRATION、KNOWN_ISSUES、DEVELOPMENT_LOG、CHAT_TRANSCRIPT。

### Known Issues（详见 docs/KNOWN_ISSUES.md，计划 0.2.0）
- 托盘配置输入框错位；无测试连接；无提供商配置档案；无获取模型列表。
- 网页无测试连接/提供商档案/获取模型；启停按钮需整合为两态；题库截断需 `[…]` + 详情页。
- 日志不够详细；数据类型需结构化扩展；无导出数据功能；OCS 识图配置(v2)未支持。
