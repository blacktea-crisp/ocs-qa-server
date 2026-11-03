# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

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
