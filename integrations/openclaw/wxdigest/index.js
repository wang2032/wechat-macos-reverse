// OpenClaw 插件：wx_digest —— 把某天「我参与过的」微信会话整理成日报。
// 真正干活的是本机 wxdigest.py：快照 → 解密 → 按会话统计 → 可选推送企业微信。
import { spawn } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const HERE = new URL(".", import.meta.url).pathname;
const PYSRC = process.env.WXR_PYSRC || `${HERE}../../src`;
const MODULE = process.env.WXR_MODULE || "wxr.digest";

function runPy(args, timeoutMs = 120000) {
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
  name: "wx_digest",
  label: "微信日报",
  description:
    "整理某一天「我参与过的」微信群聊与私聊（= 我在那个会话里发过消息），输出每条会话的消息量、你发了几条、双方最后一句话、谁还没回。只读本地微信库，不需要微信客户端配合。可 push 到企业微信。",
  parameters: {
    type: "object",
    properties: {
      date: { type: "string", description: "YYYY-MM-DD，默认今天" },
      push: { type: "boolean", description: "整理完顺便推送到企业微信（需要配置 webhook）" },
      json: { type: "boolean", description: "输出结构化 JSON 而不是文本，便于自己再加工" }
    },
    additionalProperties: false
  },
  async execute(_toolCallId, params = {}) {
    const args = [];
    if (params.date) args.push("--date", String(params.date));
    if (params.json) args.push("--json");
    if (params.push) args.push("--push");
    const { code, out, err } = await runPy(args);
    const text = (out || "").trim() || (err || "").trim() || "(没有输出)";
    return {
      content: [{ type: "text", text }],
      details: { exitCode: code, stderr: err.slice(0, 2000) }
    };
  }
};

const base = {
  id: "wx-digest",
  name: "WeChat Digest",
  description: "整理「我参与过的」微信会话，产出每日日报，可推送到企业微信。",
  register(api) {
    api.registerTool(tool, { name: tool.name });
  }
};

export default definePluginEntry(base);
