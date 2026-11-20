#!/usr/bin/env python3
"""Generate static HTML transcripts from export/wechat.db."""
import sqlite3, html, re, json, pathlib, datetime, hashlib
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE/"export"; CH = OUT/"chats"; CH.mkdir(exist_ok=True)
db = sqlite3.connect(OUT/"wechat.db"); db.row_factory = sqlite3.Row

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#e6e8eb;--txt:#1d2129;--mut:#86909c;--in:#fff;--out:#d5f5c8;--me:#07c160}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 -apple-system,"PingFang SC","Helvetica Neue",sans-serif;background:var(--bg);color:var(--txt)}
header{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center}
header b{font-size:15px}header small{color:var(--mut)}
.wrap{max-width:860px;margin:0 auto;padding:16px 16px 80px}
.day{text-align:center;color:var(--mut);font-size:12px;margin:22px 0 10px}
.m{display:flex;margin:8px 0;gap:8px;align-items:flex-start}
.body{flex:1;min-width:0;display:flex;flex-direction:column;align-items:flex-start}
.out .body{align-items:flex-end}
.m.out{flex-direction:row-reverse}
.av{width:34px;height:34px;border-radius:6px;flex:0 0 34px;display:flex;align-items:center;justify-content:center;
    font-size:13px;color:#fff;background:#9aa7b1;font-weight:600}
.b{max-width:min(640px,86%);background:var(--in);border:1px solid var(--line);border-radius:8px;padding:8px 11px;
   white-space:pre-wrap;word-break:break-word}
.out .b{background:var(--out);border-color:#bfe6ae}
.sn{font-size:11px;color:var(--mut);margin:0 0 2px}
.sys{text-align:center;color:var(--mut);font-size:12px;margin:10px 0}
.tag{display:inline-block;font-size:11px;color:#5b6b7c;background:#eef1f4;border-radius:3px;padding:0 5px;margin-right:4px}
a{color:#165dff;word-break:break-all}
input.q{flex:1;max-width:280px;border:1px solid var(--line);border-radius:6px;padding:6px 10px;font-size:13px}
"""

def esc(s): return html.escape(s or "", quote=False)
def link(s):
    return re.sub(r"(https?://[^\s<>\"]+)", lambda m: f'<a href="{esc(m.group(1))}" target="_blank">{esc(m.group(1))}</a>', esc(s))

def slug(u, name):
    h = hashlib.md5(u.encode()).hexdigest()[:12]
    safe = re.sub(r"[^\w\u4e00-\u9fff·\-]+", "_", name)[:40].strip("_") or "chat"
    return f"{safe}-{h}"

chats = list(db.execute("select * from chats order by last_ts desc"))
index, made = [], 0
for c in chats:
    rows = list(db.execute("select local_id,ts,sender_name,direction,type,text from messages where chat=? order by ts", (c["username"],)))
    if not rows: continue
    fn = slug(c["username"], c["name"]) + ".html"
    parts, day = [], None
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d")
        if d != day:
            day = d; parts.append(f'<div class="day">{d}</div>')
        t = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
        if r["type"] == "系统":
            parts.append(f'<div class="sys">{esc(re.sub(r"<[^>]+>","",r["text"]))}</div>'); continue
        cls = "m out" if r["direction"] == "out" else "m"
        initial = esc((r["sender_name"] or "?")[0])
        body = link(r["text"])
        if r["type"] not in ("文本",):
            body = f'<span class="tag">{esc(r["type"])}</span>{body}'
        sn = "" if r["direction"] == "out" else f'<div class="sn">{esc(r["sender_name"])}</div>'
        parts.append(f'<div class="{cls}" id="m{r["local_id"]}" data-t="{esc(t)}"><div class="av">{initial}</div>'
                     f'<div class="body">{sn}<div class="b" title="{esc(t)}">{body}</div></div></div>')
    title = esc(c["name"])
    page = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}</style>
<header><a href="../index.html" style="text-decoration:none;color:var(--mut)">← 返回</a>
<b>{title}</b><small>{len(rows)} 条 · {datetime.datetime.fromtimestamp(rows[0]["ts"]).strftime("%Y-%m-%d")} → {datetime.datetime.fromtimestamp(rows[-1]["ts"]).strftime("%Y-%m-%d")}</small>
<input class="q" placeholder="在本会话中过滤（回车定位）" onkeydown="if(event.key==='Enter')f(this.value)">
</header><div class="wrap" id="w">{''.join(parts)}</div>
<script>
function f(q){{document.querySelectorAll('#w .m,.day').forEach(function(e){{
  e.style.display = (!q || (e.innerText||'').toLowerCase().includes(q.toLowerCase())) ? '' : 'none';}});}}
</script></html>"""
    (CH/fn).write_text(page, encoding="utf8")
    index.append((c, fn, len(rows)))
    made += 1

cards = []
for c, fn, n in index:
    icon = {"group":"👥","official":"📣","person":"👤"}.get(c["kind"], "👤")
    last = datetime.datetime.fromtimestamp(c["last_ts"]).strftime("%m-%d %H:%M") if c["last_ts"] else ""
    cards.append(f"""<a class="c" href="chats/{fn}" data-n="{(c['name'] or '').lower()}">
<div class="i">{icon}</div><div class="x"><div class="n">{esc(c['name'])}</div>
<div class="s">{esc((c['summary'] or '')[:60])}</div></div>
<div class="r"><div class="t">{last}</div><div class="cnt">{n} 条</div></div></a>""")

idxc = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>微信聊天记录 {len(index)} 个会话</title><style>{CSS}
.c{{display:flex;gap:12px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:8px;
    padding:10px 12px;margin:8px 0;text-decoration:none;color:inherit}}
.c:hover{{border-color:#c9d2dc}}.i{{font-size:20px}}.x{{flex:1;min-width:0}}
.n{{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.s{{color:var(--mut);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.r{{text-align:right;color:var(--mut);font-size:12px}}.cnt{{margin-top:2px}}
</style>
<header><b>微信聊天记录</b><small>{len(index)} 个会话 · {sum(n for _,_,n in index):,} 条消息</small>
<input class="q" placeholder="搜索会话名…" oninput="s(this.value)"></header>
<div class="wrap" id="l">{''.join(cards)}</div>
<script>function s(q){{document.querySelectorAll('#l .c').forEach(function(e){{
e.style.display=(!q||e.dataset.n.includes(q.toLowerCase()))?'':'none';}});}}</script></html>"""
(OUT/"index.html").write_text(idxc, encoding="utf8")
json.dump({c["username"]: fn for c, fn, _ in index}, open(OUT/"chats.json","w"), ensure_ascii=False)
print("chats rendered:", made, "total msgs:", sum(n for _,_,n in index))
