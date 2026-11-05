# OCS 接入指南（OCS Integration）

> 版本：v0.1.0
> 本文档说明如何让 OCS 网课助手（ocsjs）接入本自建题库后端。

## 1. 原理

OCS 通过「题库配置（AnswererWrapper[]）」向一个 HTTP 接口发请求获取答案。本系统提供 `/search` 接口，按 OCS 的契约返回 JSON。OCS 侧只需粘贴一份题库配置即可。

## 2. 生成题库配置

```powershell
cd ocs-qa-server
python -m scripts.export_ocs_config --host <你的IP或127.0.0.1> --port 8000 --trust prefer_trusted
```

输出会打印并写入 `ocs_config.generated.json`。

### v1 配置（纯文本，默认）
```json
[{
  "name": "自建题库",
  "homepage": "http://127.0.0.1:8000",
  "url": "http://127.0.0.1:8000/search",
  "method": "get",
  "responseType": "json",
  "data": {
    "title": "${title}",
    "type": "${type}",
    "options": "${options}",
    "answer_trust": "prefer_trusted"
  },
  "handler": "return (res)=> (res && res.code===1) ? [res.question, res.answer] : (res && res.msg ? [res.msg, undefined] : undefined)"
}]
```

### v2 配置（含识图，0.2.0+ 默认）
> **0.2.0 起默认导出 v2**，OCS 不再提示「当前配置不支持识图」。
> v2 特征：`"v": 2`、`method: "post"`、`headers` JSON、`data` 引用 `${images}` / `${suggestion_title}` / `${suggestion_options}`。
> 生成：`python -m scripts.export_ocs_config --host <IP> --port 8000`（默认 v2）；如需纯文本 v1 加 `--version v1`。
> 后端 `/search` 的 POST 已接收 `images`（data URL 数组）并交给识图。

```json
[{
  "name": "自建题库(含识图)",
  "homepage": "http://127.0.0.1:8000",
  "url": "http://127.0.0.1:8000/search",
  "method": "post",
  "v": 2,
  "responseType": "json",
  "headers": { "Content-Type": "application/json" },
  "data": {
    "title": "${title}", "type": "${type}", "options": "${options}",
    "answer_trust": "prefer_trusted",
    "images": "${images}",
    "suggestion_title": "${suggestion_title}",
    "suggestion_options": "${suggestion_options}"
  },
  "handler": "return (res)=> (res && res.code===1) ? [res.question, res.answer] : (res && res.msg ? [res.msg, undefined] : undefined)"
}]
```

## 3. 接入步骤（OCS 侧）

1. 启动后端（托盘「启动服务」或 `python -m uvicorn app.main:app`）。
2. 打开 OCS 的「题库配置」，选择粘贴模式（**ocsjs v5.2.7 起不再支持从 URL 加载，必须粘贴 JSON**）。
3. 粘贴上面的 JSON。
4. **`@connect` 放行域名**：OCS 脚本的元信息 `@connect` 需包含题库服务器域名/IP；否则改为脚本管理器设置 `@connect 模式：宽松`，或使用官方「全域名通用版」脚本。
5. 在任意网课页面点击自动答题，脚本会请求 `/search`。

## 4. 「当前配置不支持识图」说明

ocsjs 判断「支持识图」的条件（见 ocsjs `isAnswererWrapperSupportImageOptimize`）：
- 请求方法为 **post**，且
- `data` 中引用了 `${images}` / `${suggestion_title}` / `${suggestion_options}`（占位符或字段 handler 读取 `env.images` 等）。

v1 配置是 `get` 且不含上述字段，故 OCS 判为不支持识图 —— 这是**已知问题 O1**，方案见 `KNOWN_ISSUES.md`，将在 **0.2.0** 提供 v2 配置解决。

## 5. 返回契约（/search）

请求：
- `GET /search?title=&type=&options=&answer_trust=`
- `POST /search` body: `{title, type, options, images?, answer_trust?}`

响应（JSON）：
```json
{ "code": 1, "question": "题干", "answer": "答案", "answer_status": "trusted|candidate|conflict", "source": "store|llm", "msg": null, "request_id": "..." }
```
- `code=1` 有答案；`code=0` 无答案，`msg` 为提示。
- 多选答案以 `#` 连接（如 `A选项#C选项`），与 ocsjs `splitAnswer` 兼容。

## 6. OCS 侧题库缓存机制说明（理解命中口径）

> 本节基于 ocsjs v5.2.7 源码（`packages/scripts/src/projects/background.ts`、`common.ts`、`utils/work.ts`）实证整理，帮助理解「为什么有些题不会请求到我们后端」。

ocsjs 内置一个**客户端内存题库缓存**：答题时先查缓存，命中直接返回、**不请求任何题库**；答题完成后再把「题目+答案」写回缓存。默认开启（设置项 `enableQuestionCaches`）。

### 6.1 数据结构
```ts
type QuestionCache = { title: string; answer: string; from: string; homepage: string; ai?: boolean };
const localQuestionCaches: QuestionCache[] = [];  // 顶层帧内存数组
```

### 6.2 关键设计
1. **纯内存、不持久化**：页面关闭即清空。历史上曾存 GM 存储，因大数组全量序列化耗时改为内存；跨页面/刷新不保留。
2. **多 iframe 只存顶层帧**：缓存本体仅在顶层帧，iframe 经 `cors.defineTopFunction` 路由到顶层帧读写（避免 tab 存储写放大）。
3. **容量三重限制**：
   | 维度 | 上限 | 超限处理 |
   |---|---|---|
   | 单条 | 64 KB（title+answer UTF-8） | **直接跳过不入库** |
   | 条数 | 200 条 | 截断 |
   | 总量 | 1 MB | 从尾部（最旧）剔除至达标 |

### 6.3 写入
- 触发：答题**完成**（`finish === true`）后写入。
- 去重：`title + answer` 相同则不重复插入；新条目 `unshift` 到头部（保留最新，尾部淘汰=LRU 倾向）。
- 受 `enableQuestionCaches` 开关控制。

### 6.4 读取（`searchAnswerInCaches`）
```
if (缓存开关关闭) → 直接查题库
results = 查缓存(title)          // 顶层帧/路由
if (results 为空) → 查题库（此时才有 period 延迟，默认 3s）
else → 直接返回缓存结果（不发请求、不等待）
```
- **匹配方式：`cache.title.trim() === title.trim()` 精确相等**（不做相似/归一化）。

### 6.5 与我们后端的关系（重要）
- OCS 缓存是**客户端内存缓存**，与服务端题库是两层：**同一页面里重复题命中缓存 → 根本不经过我们后端**。
- 因此我们后端的 `store_hit`（题库命中率）统计，反映的是「**OCS 缓存没拦下的请求**」，而非全部答题。
- 兼容性：我们后端用「归一化 + 相似度 + 选项集合校验」，比 OCS 的精确匹配更宽容，二者互补。
- 可选优化（0.2.0+）：后端也可加进程内 LRU 热缓存（参考 200 条/1MB 上限）减少 DB 查询；并在响应中带 `cache` 语义标识便于诊断。

---

## 7. 常见问题

| 现象 | 排查 |
|---|---|
| OCS 请求失败/超时 | 后端是否在跑；`/health` 是否 200；`@connect` 是否放行域名 |
| 一直返回 code=0 | 题库未命中且大模型不可用（检查 LLM 配置/网络）；先 `python -m scripts.seed` 灌示例 |
| 跨机访问连不上 | 后端默认绑 `127.0.0.1`，跨机需把 `.env` 的 `HOST=0.0.0.0` 并放行防火墙端口 |
| 识图不触发 | 0.1.0 不支持；等 0.2.0 的 v2 配置 |
