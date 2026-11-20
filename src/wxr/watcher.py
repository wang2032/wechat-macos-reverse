#!/usr/bin/env python3
"""增量监听微信新消息 → 只推给你自己（系统通知 / 企微机器人 / 本地 inbox）。

    python3 watch_new.py --seed      # 第一次：只记录游标，不推送
    python3 watch_new.py --once      # 跑一次
    python3 watch_new.py             # 常驻
"""
import argparse, datetime, hashlib, json, pathlib, re, sys, time

from . import config as _cfg
from . import notify, wx

STATE = _cfg.state_path("watch_state.json")
LOGF = _cfg.state_path("new_messages.jsonl")
TYPES = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 48: "位置", 49: "卡片", 50: "通话", 10000: "系统"}


def load_state():
    return json.load(open(STATE)) if STATE.exists() else {"chats": {}}


def save_state(s):
    tmp = STATE.with_suffix(".tmp")
    json.dump(s, open(tmp, "w"), ensure_ascii=False, indent=1)
    tmp.replace(STATE)


def label(lt):
    lt = int(lt or 0)
    if (lt & 0xFFFFFFFF) == 49 or lt > 10000:
        return "卡片"
    return TYPES.get(lt, f"类型{lt}")


def collect(cfg, state):
    account = cfg.get("account", wx.DEFAULT_ACCOUNT)
    key = wx.my_key(account)
    base = wx.dbdir(account)
    mdir, sdir, cdir = base/"message", base/"session", base/"contact"
    snap = wx.snapshot([mdir/"message_0.db", mdir/"message_0.db-wal", mdir/"message_0.db-shm",
                        sdir/"session.db", sdir/"session.db-wal", sdir/"session.db-shm",
                        cdir/"contact.db"], dest="/tmp/wxsnap_watch")
    db = snap/"message_0.db"
    tables = [r[0] for r in wx.q(db, "select name from sqlite_master where type='table' and name like 'Msg_%'", key)]
    uname = {u: (r or n or u) for u, r, n in wx.q(snap/"contact.db", "select username, remark, nick_name from contact", key)} \
        if (snap/"contact.db").exists() else {}
    sess = [r[0] for r in wx.q(snap/"session.db", "select username from SessionTable", key)] \
        if (snap/"session.db").exists() else []
    h2u = {hashlib.md5(u.encode()).hexdigest(): u for u in sess}
    idmap = {int(r[0]): r[1] for r in wx.q(db, "select rowid, user_name from Name2Id", key)}
    me = wx.me(account)

    first = not state["chats"]
    parts, seeded = [], {}
    for t in tables:
        last = state["chats"].get(t)
        if last is None:
            seeded[t] = int(wx.q(db, f'select coalesce(max(local_id),0) from "{t}"', key)[0][0])
            continue
        parts.append(f'select "{t}" as t, local_id, create_time, real_sender_id, local_type, '
                     f'message_content, WCDB_CT_message_content from "{t}" where local_id > {int(last)}')
    if first or not parts:
        for t, v in seeded.items():
            state["chats"][t] = v
        save_state(state)
        return []
    rows = wx.q(db, " union all ".join(parts) + " order by create_time", key)
    out = []
    for t, lid, ts, rsid, lt, content, ctype in rows:
        state["chats"][t] = max(int(state["chats"].get(t, 0)), int(lid))
        text = wx.text_of(content, ctype)
        sender, body = wx.split_sender(text)
        who = idmap.get(int(rsid or 0), sender) if (rsid and str(rsid).isdigit()) else sender
        chat = h2u.get(t.replace("Msg_", ""), "")
        typ = label(lt)
        body = body.strip()
        if typ == "卡片":
            m = re.search(r"<title>(.*?)</title>", body, re.S)
            body = (m.group(1).strip() if m else "")
        elif typ != "文本":
            body = ""
        out.append(dict(chat=chat, chat_name=uname.get(chat, chat or t), who=uname.get(who, who),
                        direction="out" if who == me else "in", type=typ,
                        ts=int(ts or 0), local_id=int(lid), text=body))
    save_state(state)
    return out


def interesting(m, cfg):
    w = cfg.get("watch", {})
    if m["direction"] == "out":
        return False
    if m["chat"].endswith("@chatroom"):
        mode = w.get("groups", "keywords")
        if mode == "off":
            return False
        if mode == "keywords":
            kws = w.get("keywords") or []
            return any(k in m["text"] for k in kws)
    if m["chat"] in ("filehelper",):
        return False
    return True


def render(msgs):
    """按会话聚合，一个会话一条通知。"""
    by = {}
    for m in msgs:
        by.setdefault(m["chat"], []).append(m)
    out = []
    for chat, items in by.items():
        name = items[0]["chat_name"]
        lines = []
        for m in items[-3:]:
            body = m["text"].replace("\n", " ")
            lines.append(f"{m['who']}: [{m['type']}] {body[:80]}".replace("[] ", ""))
        out.append((f"{name}（{len(items)} 条）", "\n".join(lines)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    cfg = notify.load_cfg()
    state = load_state()
    if a.seed:
        state = {"chats": {}}
        collect(cfg, state)
        print(f"seeded {len(state['chats'])} chats")
        return
    if a.once:
        msgs = collect(cfg, state)
        hits = [m for m in msgs if interesting(m, cfg)]
        for m in msgs:
            with open(LOGF, "a") as f:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"new={len(msgs)} notify={len(hits)}")
        for m in hits:
            print(f"  {m['chat_name']} / {m['who']} / {m['type']} / {m['text'][:60]}")
        for title, body in render(hits):
            notify.send(title, body, cfg)
        return
    iv = int(cfg.get("watch", {}).get("interval_seconds", 60))
    print(f"watching every {iv}s, ctrl-c to stop")
    while True:
        try:
            msgs = collect(cfg, state)
            hits = [m for m in msgs if interesting(m, cfg)]
            for m in msgs:
                with open(LOGF, "a") as f:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
            for title, body in render(hits):
                notify.send(title, body, cfg)
            if hits:
                print(f"[{datetime.datetime.now():%H:%M:%S}] pushed {len(hits)}")
        except Exception as e:
            print(f"[{datetime.datetime.now():%H:%M:%S}] error: {e}", file=sys.stderr)
        time.sleep(iv)


if __name__ == "__main__":
    main()
