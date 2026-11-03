// 共享配置与 API 封装（独立前端，仅通过 HTTP 调后端管理 API）
const CONFIG = {
  // 题库后端地址（管理 API 所在）
  API_BASE: localStorage.getItem("ocs_api_base") || "http://127.0.0.1:8000",
  // supervisor 地址（服务启停）
  SUPERVISOR_BASE: localStorage.getItem("ocs_supervisor_base") || "http://127.0.0.1:8010",
  // 管理 Token
  TOKEN: localStorage.getItem("ocs_admin_token") || "changeme",
};

function setConfig(key, value) {
  if (key === "API_BASE") localStorage.setItem("ocs_api_base", value);
  if (key === "SUPERVISOR_BASE") localStorage.setItem("ocs_supervisor_base", value);
  if (key === "TOKEN") localStorage.setItem("ocs_admin_token", value);
  location.reload();
}

async function api(path, opts = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json", "X-Admin-Token": CONFIG.TOKEN },
    opts.headers || {}
  );
  const res = await fetch(CONFIG.API_BASE + path, { ...opts, headers });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`${res.status} ${t}`);
  }
  return res.json();
}

async function supervisor(path, method = "GET") {
  const res = await fetch(CONFIG.SUPERVISOR_BASE + path, { method });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function statusTag(s) {
  if (!s) return "";
  return `<span class="tag ${s}">${s}</span>`;
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

// 顶部导航
function renderTopbar(active) {
  const links = [
    ["index.html", "仪表盘"],
    ["questions.html", "题库管理"],
    ["logs.html", "日志"],
    ["settings.html", "设置"],
  ];
  return el(`
    <div class="topbar">
      <span class="logo">⚙ OCS 题库管理台</span>
      <nav>${links
        .map(([href, name]) => `<a href="${href}" class="${href === active ? "active" : ""}">${name}</a>`)
        .join("")}</nav>
      <span class="spacer"></span>
      <span class="muted mono">${CONFIG.API_BASE}</span>
    </div>
  `);
}
