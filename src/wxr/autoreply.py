#!/usr/bin/env python3
"""自动回复引擎。

只在「明确点开」的会话里工作：对方最后一条不是我发的、且是新的，就用
llm.suggest() 生成一句，按配置发出去（dry_run 时只记录）。

默认：总开关关、dry_run 开。配置存在 config.json 的 autoreply 段：
  {"enabled": false, "dry_run": true, "chats": {"<username>": true},
   "min_gap": 45, "max_per_hour": 12, "max_age": 600}
"""
import pathlib
import threading
import time
import traceback

from . import config as _cfg
from . import core, llm

LOG = _cfg.state_path("autoreply.log")
_state = {}          # chat -> 已处理到的那条 ts
_sent_times = []     # 滑动窗口，用来限速
_thread = None
_lock = threading.Lock()


def cfg():
    c = (core.cfg().get("autoreply") or {})
    return {
        "enabled": bool(c.get("enabled", False)),
        "dry_run": bool(c.get("dry_run", True)),
        "chats": dict(c.get("chats") or {}),
        "min_gap": int(c.get("min_gap", 45)),
        "max_per_hour": int(c.get("max_per_hour", 12)),
        "max_age": int(c.get("max_age", 600)),
    }


def set_state(enabled=None, dry_run=None, chat=None, on=None):
    c = core.cfg()
    ar = c.setdefault("autoreply", {})
    if enabled is not None:
        ar["enabled"] = bool(enabled)
    if dry_run is not None:
        ar["dry_run"] = bool(dry_run)
    if chat:
        ar.setdefault("chats", {})[chat] = bool(on)
    core.save_cfg(c)
    return cfg()


def log(msg):
    try:
        with LOG.open("a") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def _reply(chat, msgs):
    convo = "\n".join(
        f"{'我' if m['mine'] else m['from']}: {m['text'] or '[' + m['type'] + ']'}"
        for m in msgs[-14:]
    )
    if chat.endswith("@chatroom"):
        hint = "这是群聊，一般只回 3-6 个字，少用语气词，别抢话。"
    else:
        hint = f"这是私聊，对方是 {msgs[-1]['from']}，可以软一点。"
    sugg = llm.suggest(convo, hint=hint)
    return (sugg[0].strip() if sugg else "") or None


def _rate_ok(max_per_hour):
    now = time.time()
    with _lock:
        _sent_times[:] = [t for t in _sent_times if now - t < 3600]
        return len(_sent_times) < max_per_hour


def tick():
    c = cfg()
    if not c["enabled"]:
        return
    ax = core.ax_status()
    for chat, on in c["chats"].items():
        if not on:
            continue
        try:
            msgs = core.messages(chat, limit=6)
        except Exception:
            continue
        if not msgs:
            continue
        last = msgs[-1]
        if _state.get(chat) == last["ts"]:
            continue
        if last["mine"]:
            _state[chat] = last["ts"]
            continue
        if time.time() - last["ts"] > c["max_age"]:
            _state[chat] = last["ts"]
            continue
        if time.time() - _state.get(chat + ":at", 0) < c["min_gap"]:
            continue
        if not _rate_ok(c["max_per_hour"]):
            log("限速：一小时内回太多了，暂停")
            return
        text = _reply(chat, msgs)
        if not text:
            continue
        if c["dry_run"] or not ax["trusted"]:
            reason = "dry" if c["dry_run"] else "no-ax"
            log(f"[{reason}] {chat} ← {(last['text'] or '[' + last['type'] + ']')[:40]!r} → {text!r}")
        else:
            r = core.send(chat, text)
            log(f"[send] {chat} → {text!r} ok={r.get('ok')} err={str(r.get('err'))[:80]}")
            with _lock:
                _sent_times.append(time.time())
        _state[chat] = last["ts"]
        _state[chat + ":at"] = time.time()


def _loop():
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(4)


def start():
    global _thread
    if _thread:
        return
    _thread = threading.Thread(target=_loop, daemon=True, name="autoreply")
    _thread.start()


if __name__ == "__main__":
    start()
    while True:
        time.sleep(3600)
