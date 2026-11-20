#!/usr/bin/env python3
"""微信日报：某一天的消息量、活跃会话、还没回的私聊。

    python3 daily.py            # 今天
    python3 daily.py --date 2026-11-17 --notify
"""
import argparse, datetime, hashlib, json, pathlib, re, sys

from . import config as _cfg
from . import notify, wx

TYPES = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 48: "位置", 50: "通话", 10000: "系统"}


def day_bounds(d):
    s = datetime.datetime.combine(d, datetime.time.min)
    return int(s.timestamp()), int((s + datetime.timedelta(days=1)).timestamp())


def build(d, cfg):
    account = cfg.get("account", wx.DEFAULT_ACCOUNT)
    key = wx.my_key(account)
    base = wx.dbdir(account)
    snap = wx.snapshot([base/"message/message_0.db", base/"message/message_0.db-wal", base/"message/message_0.db-shm",
                        base/"contact/contact.db", base/"session/session.db"], dest=str(_cfg.state_path("snap_daily")))
    db = snap/"message_0.db"
    names = {u: (r or n or u) for u, r, n in wx.q(snap/"contact.db", "select username, remark, nick_name from contact", key)}
    h2u = {hashlib.md5(u.encode()).hexdigest(): u for u, in
           wx.q(snap/"session.db", "select username from SessionTable", key)}
    idmap = {int(r[0]): r[1] for r in wx.q(db, "select rowid, user_name from Name2Id", key)}
    me = wx.me(account)
    tables = [r[0] for r in wx.q(db, "select name from sqlite_master where type='table' and name like 'Msg_%'", key)]
    a, b = day_bounds(d)
    parts = [f'select "{t}" as t, local_id, create_time, real_sender_id, local_type, message_content, '
             f'WCDB_CT_message_content from "{t}" where create_time >= {a} and create_time < {b}' for t in tables]
    rows = wx.q(db, " union all ".join(parts), key)
    per = {}
    types = {}
    for t, lid, ts, rsid, lt, content, ctype in rows:
        chat = h2u.get(t[4:], "")
        who = idmap.get(int(rsid or 0)) if str(rsid or "").isdigit() else None
        d_ = per.setdefault(chat, dict(n=0, inn=0, out=0))
        d_["n"] += 1
        d_["out" if who == me else "inn"] += 1
        lt = int(lt or 0)
        k = "卡片" if (lt & 0xFFFFFFFF) == 49 or lt > 10000 else TYPES.get(lt, "其他")
        types[k] = types.get(k, 0) + 1
    # 每个会话的最后一条（全库，不只今天），找「还没回的私聊」
    latest = wx.q(db, " union all ".join([
        f'select "{t}", local_id, create_time, real_sender_id, local_type, message_content, WCDB_CT_message_content '
        f'from "{t}" where local_id = (select max(local_id) from "{t}")' for t in tables]), key)
    pending = []
    for t, lid, ts, rsid, lt, content, ctype in latest:
        lt = int(lt or 0)
        chat = h2u.get(t[4:], "")
        who = idmap.get(int(rsid or 0)) if str(rsid or "").isdigit() else None
        if who == me or not chat or chat.endswith("@chatroom"):
            continue
        if not ((lt & 0xFFFFFFFF) == 1):
            continue
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(int(ts or 0)))
        if age < datetime.timedelta(hours=2) or age > datetime.timedelta(days=7):
            continue
        txt = wx.split_sender(wx.text_of(content, ctype))[1]
        txt = re.sub(r"<[^>]+>", "", txt).replace("\n", " ").strip()[:40]
        pending.append((names.get(chat, chat), int(ts), txt, age))
    per = {k: v for k, v in per.items() if v["n"]}
    return per, types, pending, names


def render(d, per, types, pending, names):
    tot = sum(v["n"] for v in per.values())
    inn = sum(v["inn"] for v in per.values())
    out = sum(v["out"] for v in per.values())
    top = sorted(per.items(), key=lambda kv: -kv[1]["n"])[:6]
    lines = [f"📅 {d} 微信日报", f"消息 {tot:,} 条（收 {inn:,} / 发 {out:,}）　活跃会话 {len(per)} 个", ""]
    for chat, v in top:
        lines.append(f"· {names.get(chat, chat)}：{v['n']} 条")
    if types:
        lines.append("")
        lines.append("类型：" + "、".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda kv: -kv[1])[:5]))
    if pending:
        lines.append("")
        lines.append("⏳ 还没回：")
        for name, ts, txt, age in sorted(pending, key=lambda x: -x[1])[:5]:
            h = int(age.total_seconds() // 3600)
            lines.append(f"· {name}（{h} 小时前）：{txt or '[非文本]'}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args()
    cfg = notify.load_cfg()
    d = datetime.date.fromisoformat(a.date) if a.date else datetime.date.today()
    per, types, pending, names = build(d, cfg)
    text = render(d, per, types, pending, names)
    print(text)
    if a.notify:
        notify.send(f"微信日报 {d}", text, cfg)
