#!/usr/bin/env python3
"""本地查看器：静态聊天记录 + 全局搜索。 用法: python3 serve.py [port]"""
import json, sqlite3, sys, urllib.parse, datetime, pathlib
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from .. import config as _cfg

OUT = _cfg.export_dir()
PORT = int(sys.argv[1]) if len(sys.argv)>1 else 8765
MAP = json.load(open(OUT/"chats.json"))

class H(SimpleHTTPRequestHandler):
    def __init__(self,*a,**k): super().__init__(*a, directory=str(OUT), **k)
    def log_message(self,*a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/search":
            return self.api_search(urllib.parse.parse_qs(u.query))
        if u.path == "/":
            self.path = "/index.html"
        return super().do_GET()
    def api_search(self, qs):
        q = (qs.get("q",[""])[0] or "").strip()
        limit = min(int(qs.get("limit",["100"])[0]), 500)
        chat = qs.get("chat",[None])[0]
        db = sqlite3.connect(OUT/"wechat.db"); db.row_factory = sqlite3.Row
        sql = "select m.chat,m.local_id,m.ts,m.sender_name,m.direction,m.type,m.text,c.name from messages m join chats c on c.username=m.chat"
        args, where = [], []
        if q: where.append("m.text like ?"); args.append(f"%{q}%")
        if chat: where.append("m.chat=?"); args.append(chat)
        if where: sql += " where " + " and ".join(where)
        sql += " order by m.ts desc limit ?"; args.append(limit)
        rows = []
        for r in db.execute(sql, args):
            fn = MAP.get(r["chat"], "")
            rows.append(dict(chat=r["chat"], name=r["name"], file=fn, mid=r["local_id"],
                             ts=datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M"),
                             sender=r["sender_name"], text=r["text"][:300],
                             dir=r["direction"], type=r["type"]))
        body = json.dumps({"q":q,"count":len(rows),"rows":rows}, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

print(f"http://127.0.0.1:{PORT}  (Ctrl-C 退出)")
ThreadingHTTPServer(("127.0.0.1",PORT), H).serve_forever()
