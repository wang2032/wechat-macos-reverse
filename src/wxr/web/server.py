#!/usr/bin/env python3
"""微信智能助手 · 本地服务（stdlib，无第三方依赖）。

  python3 server.py            # http://127.0.0.1:8777
  python3 server.py --port 9000

接口：
  GET  /                    页面
  GET  /api/status          微信/授权/模型 状态
  GET  /api/chats           会话列表
  GET  /api/messages?chat=&limit=&after=
  GET  /api/summary?chat=&days=&ai=0|1
  GET  /api/suggest?chat=   给最近对方消息生成回复建议
  POST /api/send            {chat, text, dry}
"""
import argparse, json, pathlib, re, sys, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import autoreply, core, llm

HERE = pathlib.Path(__file__).resolve().parent
UI = HERE / "ui.html"


def _summary_local(chat, days=2):
    msgs = core.messages(chat, limit=400)
    if not msgs:
        return "这个会话没有可读消息。"
    nm = core.names()
    import collections, time
    cut = time.time() - days * 86400
    recent = [m for m in msgs if m["ts"] >= cut] or msgs
    cnt = collections.Counter(m["from"] for m in recent)
    types = collections.Counter(m["type"] for m in recent)
    lines = [f"近 {days} 天 {len(recent)} 条：", ""]
    lines.append("· 发言：" + "，".join(f"{k} {v}" for k, v in cnt.most_common(6)))
    lines.append("· 类型：" + "，".join(f"{k} {v}" for k, v in types.most_common(5)))
    gaps = []
    for a, b in zip(recent, recent[1:]):
        if b["ts"] - a["ts"] > 3600 * 3:
            gaps.append(b["ts"])
    if gaps:
        import datetime as dt
        lines.append("· 断点：" + "，".join(dt.datetime.fromtimestamp(t).strftime("%m-%d %H:%M") for t in gaps[-4:]))
    txt = [m for m in recent if m["text"] and m["type"] == "文本"]
    if txt:
        lines += ["", "最近几句："]
        for m in txt[-8:]:
            who = "我" if m["mine"] else m["from"]
            lines.append(f"· {who}：{m['text'][:60]}")
    last = recent[-1]
    if not last["mine"]:
        lines += ["", f"等你回复：{last['text'][:60] or '[' + last['type'] + ']'}"]
    return "\n".join(lines)


def _summary_ai(chat, days=2):
    msgs = core.messages(chat, limit=120)
    if not msgs:
        return None
    convo = "\n".join(f"{'我' if m['mine'] else m['from']}: {m['text'] or '[' + m['type'] + ']'}" for m in msgs[-80:])
    prompt = ("下面是一段微信聊天记录。用中文给我一份 5 行以内的要点：谁在说什么事、"
              "有没有需要我回的消息、有没有时间/地点/金额这类硬信息。不要客套话。\n\n" + convo)
    try:
        return llm.chat(prompt, system="你是聊天记录整理助手，只输出要点，不加评论。")
    except Exception as e:
        return f"[模型不可用] {e}"


def _search(qtext, only_chat, days, limit):
    """在会话分表里做 LIKE 搜索；给时间窗，避免全库扫。"""
    import time
    from .. import wx as _wx
    key = core._key()
    db = core._msgdb()
    chats = core.chat_list()
    if only_chat:
        chats = [c for c in chats if c["username"] == only_chat]
    cut = int(time.time() - days * 86400)
    lit = "'%" + qtext.replace("'", "''") + "%'"
    i2u = core._id2user()
    hits = []
    from concurrent.futures import ThreadPoolExecutor

    def one(c):
        try:
            rows = _wx.q(db, f"select local_id,create_time,real_sender_id,message_content,"
                             f"WCDB_CT_message_content from {c['table']} "
                             f"where create_time >= {cut} and message_content like {lit} "
                             f"order by create_time desc limit 30", key)
        except Exception:
            return []
        out = []
        for lid, ts, sid, content, ctype in rows:
            body = _wx.text_of(content, ctype) if content not in (None, "") else ""
            _, body = _wx.split_sender(body)
            body = core.clean(body)
            if body:
                out.append({"chat": c["username"], "chat_name": c["name"], "id": int(lid),
                            "ts": int(ts or 0), "wxid": i2u.get(int(sid or 0), ""), "text": body[:200]})
        return out

    with ThreadPoolExecutor(max_workers=10) as ex:
        for got in ex.map(one, chats):
            hits.extend(got)
    hits.sort(key=lambda h: -h["ts"])
    return hits[:limit]


def _search_unused(qtext, only_chat, days, limit):
    key = core._key()
    db = core._msgdb()
    chats = core.chat_list()
    i2u = core._id2user()
    hits = []
    for c in chats:
        try:
            rows = _wx.q(db, f"select local_id,create_time,real_sender_id,message_content,"
                             f"WCDB_CT_message_content from {c['table']} "
                             f"where create_time >= {cut} and message_content like {lit} "
                             f"order by create_time desc limit 50", key)
        except Exception:
            continue
        for lid, ts, sid, content, ctype in rows:
            body = _wx.text_of(content, ctype) if content not in (None, "") else ""
            _, body = _wx.split_sender(body)
            body = core.clean(body)
            if not body:
                continue
            hits.append({"chat": c["username"], "chat_name": c["name"], "id": int(lid),
                         "ts": int(ts or 0), "wxid": i2u.get(int(sid or 0), ""), "text": body[:200]})
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    hits.sort(key=lambda h: -h["ts"])
    return hits[:limit]


class H(BaseHTTPRequestHandler):
    server_version = "wxassist/1.0"

    def log_message(self, *a):
        pass

    def end_headers(self):
        # 允许 DSH 页面（不同端口）直接读这个本地服务
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        g = lambda k, d=None: (q.get(k) or [d])[0]
        try:
            if u.path in ("/", "/index.html"):
                return self._html(UI.read_text())
            if u.path == "/api/status":
                ax = core.ax_status()
                return self._json({
                    "account": core.ACCOUNT, "me": core.me(),
                    "trusted": ax["trusted"], "wechat_pid": ax["wechat_pid"],
                    "model": llm.status(),
                })
            if u.path == "/api/chats":
                return self._json({"chats": core.chat_list()})
            if u.path == "/api/messages":
                chat = g("chat") or ""
                if not chat:
                    return self._json({"error": "missing chat"}, 400)
                after = g("after")
                msgs = core.messages(chat, limit=int(g("limit", "60")),
                                     after_ts=int(after) if after else None)
                return self._json({"messages": msgs})
            if u.path == "/api/senders":
                chat = g("chat") or ""
                if not chat:
                    return self._json({"error": "missing chat"}, 400)
                msgs = core.messages(chat, limit=int(g("limit", "20000")))
                import collections
                c = collections.Counter(m["sender"] for m in msgs if m["sender"])
                disp = {}
                for m in msgs:
                    disp.setdefault(m["sender"], m["from"])
                rows = [{"wxid": k, "name": disp.get(k, k), "count": v} for k, v in c.most_common()]
                return self._json({"senders": rows, "total": len(msgs)})
            if u.path == "/api/search":
                qtext = (g("q") or "").strip()
                if not qtext:
                    return self._json({"error": "missing q"}, 400)
                only = g("chat") or ""
                days = int(g("days", "90"))
                lim = int(g("limit", "200"))
                return self._json({"hits": _search(qtext, only, days, lim)})
            if u.path == "/api/summary":
                chat = g("chat") or ""
                if not chat:
                    return self._json({"error": "missing chat"}, 400)
                days = int(g("days", "2"))
                if g("ai", "0") == "1":
                    t = _summary_ai(chat, days)
                    if t:
                        return self._json({"text": t, "ai": True})
                return self._json({"text": _summary_local(chat, days), "ai": False})
            if u.path == "/api/autoreply":
                ax = core.ax_status()
                return self._json({**autoreply.cfg(), "trusted": ax["trusted"]})
            if u.path == "/api/suggest":
                chat = g("chat") or ""
                msgs = core.messages(chat, limit=20)
                if not msgs:
                    return self._json({"suggestions": []})
                convo = "\n".join(f"{'我' if m['mine'] else m['from']}: {m['text'] or '[' + m['type'] + ']'}"
                                  for m in msgs[-14:])
                sugg = llm.suggest(convo)
                return self._json({"suggestions": sugg, "model": llm.status()})
            return self._json({"error": "not found"}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "internal"}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"error": "bad json"}, 400)
        if u.path == "/api/send":
            chat = data.get("chat") or ""
            text = (data.get("text") or "").strip()
            if not chat or not text:
                return self._json({"error": "missing chat/text"}, 400)
            return self._json(core.send(chat, text, dry=bool(data.get("dry"))))
        if u.path == "/api/autoreply":
            return self._json({"ok": True, **autoreply.set_state(
                enabled=data.get("enabled"), dry_run=data.get("dry_run"),
                chat=data.get("chat"), on=data.get("on"))})
        if u.path == "/api/config":
            c = core.cfg()
            c.update(data or {})
            core.save_cfg(c)
            return self._json({"ok": True, "config": c})
        return self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    autoreply.start()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f"微信智能助手 → http://{a.host}:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
