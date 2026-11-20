#!/usr/bin/env python3
"""把某一天「我参与过的」微信会话整理成一段可直接推送的日报。

参与 = 我在那个会话里发过至少一条消息（群聊、私聊都算）。
只读本地库：先 APFS clone 快照，再用 wxq 解密查询，不碰运行中的文件句柄。

  python3 wxdigest.py                 # 今天的日报，打印
  python3 wxdigest.py --date 2026-11-17
  python3 wxdigest.py --push          # 顺便推到企业微信（webhook 见 config.json）
  python3 wxdigest.py --json          # 结构化输出，给 agent 二次加工
"""
import argparse, datetime as dt, json, pathlib, sys

from . import config as _cfg
from . import wx  # 快照 + 只读查询 + zstd 解压

TYPE_TAG = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 48: "位置", 49: "卡片", 50: "通话", 10000: "系统"}
WD = "一二三四五六日"


def label(lt):
    base = lt & 0xFFFFFFFF
    return TYPE_TAG.get(base, f"type{base}")


def clean(body):
    """XML/卡片抽人话，去掉标签噪音。"""
    import re, html
    if not body:
        return ""
    if body.lstrip().startswith("<"):
        m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", body, re.S)
        if m:
            return html.unescape(m.group(1).strip())[:80]
        m = re.search(r"<des>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</des>", body, re.S)
        if m:
            return html.unescape(m.group(1).strip())[:80]
        return ""
    return body.strip()


def day_range(d):
    a = int(dt.datetime(d.year, d.month, d.day).timestamp())
    return a, a + 86400


def collect(account, d, names, sessions, me):
    msgdb = wx.dbdir(account)/"message/message_0.db"
    snap = wx.snapshot([msgdb] + [pathlib.Path(str(msgdb)+s) for s in ("-wal", "-shm")])
    md = snap/"message_0.db"
    key = wx.my_key(account)

    id2user = {}
    for rowid, uname in wx.q(md, "select rowid,user_name from Name2Id", key):
        if uname:
            id2user[int(rowid)] = uname

    lo, hi = day_range(d)
    active = {u: s for u, s in sessions.items() if lo - 86400 <= s["last"] < hi + 86400}
    import hashlib
    out = []
    for user in active:
        t = "Msg_" + hashlib.md5(user.encode()).hexdigest()
        try:
            rows = wx.q(md, f"select local_type,create_time,real_sender_id,"
                            f"message_content,WCDB_CT_message_content from {t} "
                            f"where create_time>={lo} and create_time<{hi} order by create_time", key)
        except RuntimeError:
            continue
        if not rows:
            continue
        msgs = []
        for lt, ts, sid, content, ctype in rows:
            body = wx.text_of(content, ctype) if content not in (None, "") else ""
            snd, body = wx.split_sender(body)
            snd = snd or id2user.get(int(sid or 0), "")
            kind = label(int(lt or 0))
            txt = clean(body)
            msgs.append(dict(ts=int(ts), sender=snd, mine=(snd == me), kind=kind, text=txt))
        mine = [m for m in msgs if m["mine"]]
        if not mine:                       # 我没说话 = 没参与
            continue
        theirs = [m for m in msgs if not m["mine"]]
        out.append(dict(
            chat=user, name=names.get(user) or sessions[user].get("summary") or user,
            is_group=user.endswith("@chatroom"),
            total=len(msgs), mine=len(mine), theirs=len(theirs),
            first=msgs[0]["ts"], last=msgs[-1]["ts"],
            my_last=next((m["text"] or f"[{m['kind']}]" for m in reversed(mine)), ""),
            their_last=next((((f"{names.get(m['sender'], m['sender'])}：") if user.endswith("@chatroom") else "")
                             + (m["text"] or f"[{m['kind']}]") for m in reversed(theirs)), ""),
            unread=next((m for m in reversed(msgs) if not m["mine"]), None) is not None
                   and not msgs[-1]["mine"],
            lines=[(m["text"] or f"[{m['kind']}]") for m in theirs if m["text"]][-3:],
        ))
    out.sort(key=lambda c: (-c["total"]))
    return out


def render(day, rows, me):
    head = (f"微信日报 · {day.month}月{day.day}日 周{WD[day.weekday()]}\n"
            f"你参与了 {len(rows)} 个会话，其中的消息合计 {sum(r['total'] for r in rows)} 条")
    groups = [r for r in rows if r["is_group"]]
    people = [r for r in rows if not r["is_group"]]
    lines = [head]
    for title, chunk in (("群里", groups), ("私聊", people)):
        if not chunk:
            continue
        lines.append(f"\n【{title}】")
        for r in chunk[:12]:
            tag = "（待回）" if r["unread"] else ""
            lines.append(f"· {r['name']}{tag} — {r['total']} 条，你 {r['mine']}")
            if r["their_last"]:
                lines.append(f"  对方最后：{r['their_last'][:60]}")
            if r["my_last"]:
                lines.append(f"  你最后：{r['my_last'][:60]}")
    pending = [r for r in people if r["unread"]]
    if pending:
        lines.append("\n【还没回】")
        for r in pending[:8]:
            lines.append(f"· {r['name']}：{r['their_last'][:50]}")
    return "\n".join(lines)


def push(text, cfg):
    url = cfg.get("wecom_webhook") or ""
    if not url:
        print("[push] config.json 里没有 wecom_webhook，跳过", file=sys.stderr)
        return False
    from . import notify
    notify._wecom(url, "", text)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--account", default=None)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--notify", action="store_true", help="本机通知 + 追加到 selfnotify/inbox.md")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    cfg_path = _cfg.state_path("config.json")
    cfg = json.load(open(cfg_path)) if cfg_path.exists() else _cfg.load()
    names = wx.names(a.account)
    sessions = wx.chats(a.account)
    me = wx.me(a.account)
    rows = collect(a.account, day, names, sessions, me)

    if a.json:
        print(json.dumps(dict(date=str(day), chats=rows), ensure_ascii=False, indent=1))
        return
    text = render(day, rows, me)
    print(text)
    outdir = _cfg.data_dir()/"digest"
    outdir.mkdir(exist_ok=True)
    (outdir/f"{day.isoformat()}.txt").write_text(text)
    if a.notify:
        from . import notify
        notify.send(f"微信日报 {day.month}/{day.day}", text.replace("\n", "\n"), cfg)
    if a.push and push(text, cfg):
        print(f"\n[push] 已推送 {len(text)} 字", file=sys.stderr)


if __name__ == "__main__":
    main()
