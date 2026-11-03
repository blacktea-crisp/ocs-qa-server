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

### v2 配置（含识图，0.2.0）
> **当前 0.1.0 尚不支持识图配置**，OCS 会提示「当前配置不支持识图」（见下第 4 节）。
> v2 将在 0.2.0 提供：`"v": 2`、`method: "post"`、`data` 引用 `${images}` / `${suggestion_title}` / `${suggestion_options}`。

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

## 6. 常见问题

| 现象 | 排查 |
|---|---|
| OCS 请求失败/超时 | 后端是否在跑；`/health` 是否 200；`@connect` 是否放行域名 |
| 一直返回 code=0 | 题库未命中且大模型不可用（检查 LLM 配置/网络）；先 `python -m scripts.seed` 灌示例 |
| 跨机访问连不上 | 后端默认绑 `127.0.0.1`，跨机需把 `.env` 的 `HOST=0.0.0.0` 并放行防火墙端口 |
| 识图不触发 | 0.1.0 不支持；等 0.2.0 的 v2 配置 |
