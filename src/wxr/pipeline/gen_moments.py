#!/usr/bin/env python3
import sqlite3, re, json, html, datetime, pathlib

from .. import config as _cfg

OUT = _cfg.export_dir()
SRC = _cfg.out_dir()/_cfg.account()
od=sqlite3.connect(OUT/"wechat.db")
names=dict(od.execute("select username,display from contacts"))
cx=sqlite3.connect(SRC/"sns/sns.db"); cx.text_factory=bytes
rows=[(r[0], r[1], r[2] if r[2] else (r[3] or b"")) for r in cx.execute("select tid,user_name,content,pack_info_buf from SnsTimeLine")]
rows=[(t,u,(c.decode("utf8","replace") if isinstance(c,(bytes,bytearray)) else (c or ""))) for t,u,c in rows]
items=[]
for r in rows:
    xml=r[2]
    if not xml or "<TimelineObject" not in xml: continue
    def g(tag):
        m=re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
        return (m.group(1).strip() if m else "")
    try: t=int(g("createTime"))
    except Exception: t=0
    u=g("username"); desc=g("contentDesc")
    nimg=len(re.findall(r"<media>", xml))
    loc=g("poiName")
    items.append(dict(ts=t, user=u, name=names.get(u,u), text=desc, images=nimg, loc=loc))
items.sort(key=lambda x:-x["ts"])
od.execute("drop table if exists moments")
od.execute("create table moments(ts int, user text, name text, text text, images int, loc text)")
od.executemany("insert into moments values(:ts,:user,:name,:text,:images,:loc)", items)
od.commit()
def esc(s): return html.escape(s or "")
cards="".join(f'''<div class="m"><div class="h"><b>{esc(i["name"])}</b>
<span>{datetime.datetime.fromtimestamp(i["ts"]).strftime("%Y-%m-%d %H:%M")}</span></div>
<div class="t">{esc(i["text"])}</div>{"<div class=c>🖼 "+str(i["images"])+" 张图</div>" if i["images"] else ""}
{"<div class=c>📍 "+esc(i["loc"])+"</div>" if i["loc"] else ""}</div>''' for i in items if i["text"] or i["images"])
page=f"""<!doctype html><html lang=zh><meta charset=utf-8><title>朋友圈</title>
<style>body{{margin:0;font:14px/1.6 -apple-system,"PingFang SC",sans-serif;background:#f6f7f9}}
header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #e6e8eb;padding:10px 16px}}
.wrap{{max-width:720px;margin:0 auto;padding:16px}}.m{{background:#fff;border:1px solid #e6e8eb;border-radius:8px;padding:10px 14px;margin:8px 0}}
.h{{display:flex;gap:10px;color:#86909c;font-size:12px;margin-bottom:4px}}.t{{white-space:pre-wrap}}.c{{color:#86909c;font-size:12px;margin-top:4px}}</style>
<header><b>朋友圈</b> <small>{len(items)} 条 · 2026 年</small> <a href=index.html style="float:right;color:#86909c">聊天记录 →</a></header>
<div class=wrap>{cards}</div></html>"""
(OUT/"moments.html").write_text(page,encoding="utf8")
print("moments:",len(items),"->",OUT/"moments.html")
