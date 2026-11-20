// OpenClaw 插件：wx_chat —— 「我和某人/某个群，某段时间聊了什么」→ 摘要 + 原文。
// 干活的是本机 chatquery.py：快照 → 解密 → 取区间消息 → 模型总结（失败退回本地统计）。
import { spawn } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const HERE = new URL(".", import.meta.url).pathname;
const PYSRC = process.env.WXR_PYSRC || `${HERE}../../src`;
const MODULE = process.env.WXR_MODULE || "wxr.chatquery";

function runPy(args, timeoutMs = 180000) {
  return new Promise((resolve) => {
    const p = spawn("python3", ["-m", MODULE, ...args], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, PYTHONPATH: PYSRC },
    });
    let out = "", err = "";
    const t = setTimeout(() => { try { p.kill("SIGKILL"); } catch {} }, timeoutMs);
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err += d; });
    p.on("error", (e) => { clearTimeout(t); resolve({ code: -1, out, err: String(e) }); });
    p.on("close", (code) => { clearTimeout(t); resolve({ code, out, err }); });
  });
}

const tool = {
  name: "wx_chat",
  label: "微信聊天记录查询",
  description:
    "按「和谁 + 什么时间」查本地微信聊天记录并总结。who 可以是联系人备注/昵称，也可以是群名（支持模糊匹配）。时间用 from/to（YYYY-MM-DD 或 11-01）或 days/yesterday。返回：一句话总结、分条要点、待回事项、原文最后几条。只读本地库，不需要微信客户端在线。",
  parameters: {
    type: "object",
    properties: {
      who: { type: "string", description: "联系人备注/昵称或群名，例如「老婆」「周末羽毛球群」" },
      from: { type: "string", description: "起始日期 YYYY-MM-DD 或 MM-DD，默认 7 天前" },
      to: { type: "string", description: "结束日期 YYYY-MM-DD 或 MM-DD，默认现在" },
      days: { type: "number", description: "最近多少天（与 from 二选一）" },
      yesterday: { type: "boolean", description: "只看昨天" },
      by: { type: "string", description: "只看这个人发的消息（群里必须传这个才能列某人发言）" },
      ask: { type: "string", description: "想特别知道的问题，例如「最近在约什么局」" },
      json: { type: "boolean", description: "输出结构化 JSON" }
    },
    required: ["who"],
    additionalProperties: false
  },
  async execute(_toolCallId, params = {}) {
    const args = ["--who", String(params.who)];
    if (params.by) args.push("--by", String(params.by));
    if (params.from) args.push("--from", String(params.from));
    if (params.to) args.push("--to", String(params.to));
    if (params.days) args.push("--days", String(params.days));
    if (params.yesterday) args.push("--yesterday");
    if (params.ask) args.push("--ask", String(params.ask));
    if (params.json) args.push("--json");
    const { code, out, err } = await runPy(args);
    const text = (out || "").trim() || (err || "").trim() || "(没有输出)";
    return {
      content: [{ type: "text", text }],
      details: { exitCode: code, stderr: err.slice(0, 2000) }
    };
  }
};

const base = {
  id: "wx-chat",
  name: "WeChat Chat Query",
  description: "按人和时间查微信聊天记录并总结。",
  register(api) {
    api.registerTool(tool, { name: tool.name });
  }
};

export default definePluginEntry(base);
