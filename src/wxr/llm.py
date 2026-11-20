"""模型调用：DeepSeek（OpenAI 兼容）/ Anthropic / 任意兼容端点，配不上就用本地规则兜底。

配置优先级：
  1. assistant/config.json 的 llm 段（base_url / api / model / api_key 或 api_key_env）
  2. DeepSeek 官方：密钥取环境变量或 ~/.dsh-fresh/.credentials.yaml 里的 DSH_DEEPSEEK_KEY
  3. ~/.openclaw/openclaw.json 里第一个 provider

回复文风来自同目录的 skill.md（由 make_skill.py 从真实聊天记录生成）。
"""
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

from . import config as _cfg

HERE = _cfg.ROOT
CFG = _cfg.state_path("config.json")
SKILL = _cfg.skill_path()
OPENCLAW = pathlib.Path.home() / ".openclaw" / "openclaw.json"
CREDS = pathlib.Path.home() / ".dsh-fresh" / ".credentials.yaml"

DEFAULT_DEEPSEEK = {"api": "openai", "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash", "provider": "deepseek"}

_last = {"ok": None, "err": "", "ts": 0.0}
_skill_cache = {"mtime": None, "text": ""}


def _creds():
    """读 DSH 的 credentials.yaml（只取 key: value 行）。"""
    out = {}
    if CREDS.exists():
        try:
            for line in CREDS.read_text(errors="ignore").splitlines():
                m = re.match(r"\s*([A-Z0-9_]+):\s*(\S+)", line)
                if m:
                    out[m.group(1)] = m.group(2)
        except Exception:
            pass
    return out


def _conf():
    c = {}
    if CFG.exists():
        try:
            c = json.load(open(CFG)).get("llm") or {}
        except Exception:
            c = {}
    if c.get("base_url"):
        key = c.get("api_key") or ""
        if not key and c.get("api_key_env"):
            key = os.environ.get(c["api_key_env"]) or _creds().get(c["api_key_env"], "")
        if key:
            return {"api": c.get("api") or "openai", "base_url": c["base_url"].rstrip("/"),
                    "api_key": key, "model": c.get("model") or "",
                    "model_fast": c.get("model_fast") or "", "provider": "config"}
    key = os.environ.get("DSH_DEEPSEEK_KEY") or _creds().get("DSH_DEEPSEEK_KEY", "")
    if key:
        return {**DEFAULT_DEEPSEEK, "api_key": key}
    try:
        oc = json.load(open(OPENCLAW))
        provs = (oc.get("models") or {}).get("providers") or {}
        for name, p in provs.items():
            if not p.get("baseUrl") or not p.get("apiKey"):
                continue
            models = p.get("models") or []
            mid = ""
            if isinstance(models, list) and models and isinstance(models[0], dict):
                mid = models[0].get("id") or ""
            api = "anthropic" if "anthropic" in str(p.get("api", "")) else "openai"
            return {"api": api, "base_url": p["baseUrl"].rstrip("/"),
                    "api_key": p["apiKey"], "model": mid, "provider": name}
    except Exception:
        pass
    return None


def status():
    c = _conf()
    if not c:
        return {"configured": False, "ok": False, "model": "", "err": "未配置模型"}
    return {"configured": True, "ok": _last["ok"], "model": c.get("model") or "?",
            "provider": c.get("provider", "config"), "err": _last["err"]}


def _post(url, payload, headers, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(prompt, system="", temperature=0.4, max_tokens=700, retries=1, fast=False):
    c = _conf()
    if not c:
        raise RuntimeError("未配置模型")
    if fast and c.get("model_fast"):
        c = dict(c, model=c["model_fast"])
    last_err = ""
    for _ in range(retries + 1):
        try:
            if c["api"] == "anthropic":
                url = c["base_url"] + "/v1/messages"
                payload = {"model": c["model"], "max_tokens": max_tokens,
                           "temperature": temperature,
                           "messages": [{"role": "user", "content": prompt}]}
                if system:
                    payload["system"] = system
                d = _post(url, payload, {"x-api-key": c["api_key"],
                                         "anthropic-version": "2023-06-01",
                                         "Content-Type": "application/json"})
                text = "".join(b.get("text", "") for b in d.get("content", [])
                               if b.get("type") == "text")
            else:
                url = c["base_url"] + "/chat/completions"
                msgs = ([{"role": "system", "content": system}] if system else []) + \
                       [{"role": "user", "content": prompt}]
                d = _post(url, {"model": c["model"], "messages": msgs,
                                "temperature": temperature, "max_tokens": max_tokens},
                          {"Authorization": "Bearer " + c["api_key"],
                           "Content-Type": "application/json"})
                ch = (d.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                text = msg.get("content") or ""
                fin = ch.get("finish_reason")
            text = (text or "").strip()
            if fin == "length" and max_tokens < 6000:
                max_tokens *= 2
                last_err = "truncated (finish=length), retry bigger"
                continue
            if not text:
                # 推理模型把预算全花在 reasoning 上时会返回空 content
                if fin == "length" and max_tokens < 4000:
                    max_tokens *= 2
                    last_err = "empty content (finish=length), retry bigger"
                    continue
                last_err = f"empty content (finish={fin})"
                raise RuntimeError(last_err)
            _last.update(ok=True, err="", ts=time.time())
            return text
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if isinstance(e, urllib.error.HTTPError):
                try:
                    last_err += " " + e.read().decode()[:200]
                except Exception:
                    pass
            time.sleep(0.6)
    _last.update(ok=False, err=last_err[:300], ts=time.time())
    raise RuntimeError(last_err[:300])


def skill_text():
    """skill.md 有改动就重新读，方便边调边试。"""
    try:
        m = SKILL.stat().st_mtime
        if _skill_cache["mtime"] != m:
            _skill_cache["text"] = SKILL.read_text()
            _skill_cache["mtime"] = m
    except Exception:
        pass
    return _skill_cache["text"]


# ---- 本地兜底：没有模型也能给三条可以考虑的话 ----
_RULES = [
    (r"吗|呢|？|\?", ["咋了", "怎么啦", "我看看"]),
    (r"吃饭|饭|吃啥|吃啥", ["吃了", "还没呢", "你想吃啥"]),
    (r"几点|时间|什么时候|约", ["都可以", "你说", "下午吧"]),
    (r"打球|球", ["来", "几点", "在哪"]),
    (r"谢谢|感谢", ["客气", "嗯嗯", "没事"]),
    (r"在吗|在不在|忙不忙", ["在", "咋了", "说"]),
    (r"哈哈|hhh", ["哈哈哈", "笑死", "真的假的"]),
    (r"晚安|睡了|困", ["晚安", "睡吧", "早点睡"]),
]
_DEFAULT = ["嗯嗯", "好", "我看看"]


def _rules(last):
    for pat, cands in _RULES:
        if re.search(pat, last):
            return list(cands)
    return list(_DEFAULT)


def _clean(lines, n=3):
    out = []
    for raw in lines:
        s = raw.strip()
        s = re.sub(r"^[\d]+[\.\)、,，:：]\s*", "", s)          # 1. / 1) / 1、
        s = re.sub(r"^[-*·•]\s*", "", s)
        s = re.sub(r"^(我|回复|答)[:：]\s*", "", s)
        s = s.strip("「」“”\"'`* ")
        s = s.splitlines()[0].strip() if s else ""
        if not s or len(s) > 18:
            continue
        if re.search(r"抱歉|作为|AI|模型|建议|可以回复|这条", s):
            continue
        if s not in out:
            out.append(s)
        if len(out) >= n:
            break
    return out


def suggest(convo, n=3, hint=""):
    """给对话生成 n 条候选回复（按像我的程度排序），失败回落规则。hint 是场景提示。"""
    last = ""
    for line in reversed(convo.splitlines()):
        if not line.startswith("我:"):
            last = line.split(":", 1)[-1].strip()
            break
    fallback = _rules(last)
    if _conf():
        prompt = ("下面是我们在微信上的对话，最后一条是对方说的：\n\n"
                  + convo[-2000:] +
                  ("\n\n场景：" + hint if hint else "") +
                  "\n\n按 skill 里的规则，写出「我」接下来会发的那句话。"
                  "输出三行，每行一个候选，不要编号、不要引号、不要解释。")
        try:
            out = chat(prompt, system=skill_text(), temperature=0.9, max_tokens=60)
            got = _clean(out.splitlines(), n)
            for f in fallback:
                if len(got) >= n:
                    break
                if f not in got:
                    got.append(f)
            if got:
                return got
        except Exception:
            pass
    return fallback
