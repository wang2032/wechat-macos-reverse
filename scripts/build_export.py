#!/usr/bin/env python3
"""把已解密的微信库整理成可查询的数据 + 可读的聊天记录。"""
import sqlite3, os, re, json, hashlib, html, datetime, pathlib, sys
import zstdlib

ACCT = "wxid_example_0001"
SELF = "wxid_example_0001"
HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE/"out"/ACCT
OUT = HERE/"export"; CHATS = OUT/"chats"
OUT.mkdir(exist_ok=True); CHATS.mkdir(exist_ok=True)

def md5(s): return hashlib.md5(s.encode()).hexdigest()

def ts(t):
    try: return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except Exception: return ""

def dec(b):
    if not b: return ""
    s = zstdlib.decompress(b) if isinstance(b,(bytes,bytearray)) and bytes(b[:4])==b"\x28\xb5\x2f\xfd" else b
    if isinstance(s,(bytes,bytearray)): return bytes(s).decode("utf8","replace")
    return s

def strip_sender(text, sender_guess):
    """消息体形如 'wxid_xxx:\n<...>' 时剥掉前缀，返回 (sender, body)。"""
    m = re.match(r"^([A-Za-z0-9_@\-\.]{3,64}):\n", text)
    if m:
        return m.group(1), text[m.end():]
    return sender_guess, text

def _unesc(t):
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", lambda m: m.group(1), t, flags=re.S)
    return html.unescape(t).strip()

def xml_field(body, *names):
    for n in names:
        if "/@" in n:
            tag, attr = n.split("/@")
            m = re.search(rf'<{tag}[^>]*{attr}="([^"]*)"', body or "")
            if m and m.group(1).strip(): return _unesc(m.group(1))
            continue
        m = re.search(rf"<{n}[^>]*>(.*?)</{n}>", body or "", re.S)
        if m and _unesc(m.group(1)): return _unesc(m.group(1))
    return None

BASE_NAME = {1:"文本",3:"图片",34:"语音",43:"视频",47:"表情",48:"位置",49:"应用消息",10000:"系统",42:"名片",50:"通话"}
def base_type(lt):
    return lt if lt in BASE_NAME else (49 if (lt & 0xFFFFFFFF) == 49 else lt & 0xFFFFFFFF)
def type_name(lt):
    return BASE_NAME.get(base_type(lt), f"类型{lt}")

def render(body, lt):
    base = base_type(lt)
    if base == 49 or lt in (244813135921,266287972401,141733920817,8589934592049):
        t = xml_field(body, "title"); d = xml_field(body, "des"); sub = xml_field(body, "type")
        if t and d and d != t: return f"[{t}] {d}"
        if t: return t if not sub else f"[{t}]"
        return "[卡片消息]"
    if base == 1: return body.strip()
    if base == 3: return "[图片]"
    if base == 34:
        ln = xml_field(body, "voicemsg/@voicelength")
        return "[语音]"
    if base == 43: return "[视频]"
    if base == 47: return "[表情]"
    if base == 48:
        lb = xml_field(body, "location/@label") or xml_field(body, "location/@poiname")
        return f"[位置] {lb}" if lb else "[位置]"
    if base == 50:
        m = re.search(r"<!\[CDATA\[(.*?)\]\]>", body or "", re.S)
        return "[通话] " + (m.group(1) if m else "")
    if base == 10000:
        s = xml_field(body, "content")
        if s: return s
        return body.strip()[:200]
    return None

# ---------- 联系人 ----------
con = sqlite3.connect(SRC/"contact/contact.db"); con.row_factory = sqlite3.Row
contacts = {}
for r in con.execute("select username,alias,nick_name,remark,local_type,description from contact"):
    u = r["username"]
    if not u: continue
    name = (r["remark"] or r["nick_name"] or r["alias"] or u).strip()
    contacts[u] = dict(username=u, display=name, nick=r["nick_name"] or "", remark=r["remark"] or "",
                       alias=r["alias"] or "", kind=("group" if u.endswith("@chatroom") else
                       "official" if u.startswith("gh_") else "person"))
# 群成员
members = {}
try:
    for r in con.execute("select chat_room_username, member_username from chatroom_member"):
        members.setdefault(r[0], set()).add(r[1])
except Exception as e: print("chatroom_member:",e, file=sys.stderr)
con.close()

# ---------- 会话 ----------
ss = sqlite3.connect(SRC/"session/session.db"); ss.row_factory = sqlite3.Row
sessions = {}
for r in ss.execute("select username,summary,last_timestamp,unread_count,type from SessionTable"):
    sessions[r["username"]] = dict(summary=r["summary"] or "", last_ts=r["last_timestamp"] or 0, unread=r["unread_count"] or 0)
ss.close()

# ---------- 用户名 -> 表名 ----------
cands = set(contacts) | set(sessions) | set(members)
for s in list(members.values()): cands |= s
msgdb = sqlite3.connect(SRC/"message/message_0.db"); msgdb.row_factory = sqlite3.Row
id2user = {}
for r in msgdb.execute("select rowid,user_name from Name2Id"):
    if r["user_name"]: id2user[r["rowid"]] = r["user_name"]; cands.add(r["user_name"])
tables = [r[0] for r in msgdb.execute("select name from sqlite_master where type='table' and name like 'Msg_%'")]
h2u = {}
for u in cands: h2u.setdefault(md5(u), u)
table2user = {}
unresolved = []
for t in tables:
    h = t[4:]
    if h in h2u: table2user[t] = h2u[h]
    else: unresolved.append(t)
print(f"tables={len(tables)} resolved={len(table2user)} unresolved={len(unresolved)}")

# ---------- 输出库 ----------
if (OUT/"wechat.db").exists(): (OUT/"wechat.db").unlink()
od = sqlite3.connect(OUT/"wechat.db")
od.executescript("""
create table contacts(username text primary key, display text, nick text, remark text, alias text, kind text);
create table chats(username text primary key, name text, kind text, msg_count int, first_ts int, last_ts int, summary text);
create table messages(id integer primary key autoincrement, chat text, local_id int, ts int, sender text, sender_name text,
                      direction text, raw_type int, type text, text text);
create index idx_msg_chat on messages(chat, ts);
""")
od.executemany("insert into contacts values(?,?,?,?,?,?)",
               [(c["username"],c["display"],c["nick"],c["remark"],c["alias"],c["kind"]) for c in contacts.values()])
od.commit()

total = 0; chat_rows = []
for t in sorted(tables):
    user = table2user.get(t)
    if not user: continue
    info = contacts.get(user, {})
    cname = info.get("display") or sessions.get(user,{}).get("summary","") or user
    rows = []
    for r in msgdb.execute(f"select local_id,local_type,real_sender_id,create_time,message_content,compress_content from {t} order by create_time"):
        body = dec(r["message_content"]) or dec(r["compress_content"])
        snd = id2user.get(r["real_sender_id"], "")
        snd, body = strip_sender(body, snd)
        if not snd: snd = SELF if not user.endswith("@chatroom") else ""
        name = "我" if snd == SELF or snd == "" and not user.endswith("@chatroom") else (contacts.get(snd,{}).get("display") or snd)
        txt = render(body, r["local_type"]) or f"[type {r['local_type']}] {body[:120]}"
        rows.append((user, r["local_id"], r["create_time"], snd, name,
                     "out" if snd == SELF else "in", r["local_type"],
                     type_name(r["local_type"]), txt))
    if not rows: continue
    od.executemany("insert into messages(chat,local_id,ts,sender,sender_name,direction,raw_type,type,text) values(?,?,?,?,?,?,?,?,?)", rows)
    first, last = rows[0][2], rows[-1][2]
    chat_rows.append((user, cname, info.get("kind","person"), len(rows), first, last, sessions.get(user,{}).get("summary","")))
    total += len(rows)
od.executemany("insert into chats values(?,?,?,?,?,?,?)", chat_rows)
od.commit()
print(f"chats={len(chat_rows)} messages={total}")
json.dump({"chats":len(chat_rows),"messages":total,"contacts":len(contacts),"unresolved_tables":len(unresolved)},
          open(OUT/"summary.json","w"), ensure_ascii=False, indent=1)
