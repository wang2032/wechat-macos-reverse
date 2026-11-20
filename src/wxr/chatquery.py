#!/usr/bin/env python3
"""按「谁 + 时间范围」查聊天记录并总结。

用法:
  wxr ask --who "老婆" --from 2026-11-01 --to 2026-11-18
  wxr ask --who 羽毛球群 --days 7 --ask "最近在约什么局"
  wxr ask --who 老张 --yesterday
  wxr ask --who 老婆 --days 3 --no-ai      # 不调模型，只做统计
  wxr ask --who 老婆 --days 3 --json
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time

from . import config as _cfg
from . import core, llm

MAX_LIMIT = 4000


# ---------- 时间 ----------

def now_ts():
    return int(time.time())


def parse_date(s, end_of_day=False):
    s = (s or "").strip()
    if not s:
        return None
    today = dt.date.today()
    table = {"今天": today, "昨天": today - dt.timedelta(days=1),
             "前天": today - dt.timedelta(days=2)}
    if s in table:
        d = table[s]
        return int(dt.datetime.combine(d, dt.time(0 if not end_of_day else 23, 59, 59)).timestamp())
    if re.fullmatch(r"\d{1,2}-\d{1,2}", s):
        m, d = map(int, s.split("-"))
        return int(dt.datetime(today.year, m, d, 0 if not end_of_day else 23,
                               0 if not end_of_day else 59,
                               0 if not end_of_day else 59).timestamp())
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            d = dt.datetime.strptime(s, fmt)
            if end_of_day and len(s) <= 10:
                d = d.replace(hour=23, minute=59, second=59)
            return int(d.timestamp())
        except ValueError:
            continue
    raise SystemExit(f"看不懂的时间: {s}（支持 2026-11-01 / 11-01 / 今天 / 昨天 / 前天）")


def range_from_args(a):
    end = parse_date(a.to, end_of_day=True) if a.to else now_ts()
    if a.days:
        start = end - a.days * 86400
    elif a.yesterday:
        d = dt.date.today() - dt.timedelta(days=1)
        start = int(dt.datetime.combine(d, dt.time(0, 0)).timestamp())
        end = start + 86399
    elif a.from_:
        start = parse_date(a.from_)
    else:
        start = end - 7 * 86400
    if start > end:
        start, end = end, start
    return start, end


# ---------- 会话解析 ----------

_cache = {"chats": None, "at": 0}


def chats():
    if _cache["chats"] is None or time.time() - _cache["at"] > 120:
        _cache["chats"] = core.chat_list()
        _cache["at"] = time.time()
    return _cache["chats"]


def resolve(who):
    """名字 → 会话。优先精确，其次包含；同时给候选提示。"""
    who = (who or "").strip()
    if not who:
        raise SystemExit("需要 --who")
    cs = chats()
    for c in cs:
        if c["name"] == who or c["username"] == who:
            return c
    hits = [c for c in cs if who in c["name"] or who.lower() in c["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"没找到「{who}」。现有会话前 20：\n  " +
                         "\n  ".join(c["name"] for c in cs[:20]))
    raise SystemExit(f"「{who}」匹配到多个：\n  " +
                     "\n  ".join(f"{c['name']}  ({c['kind']})" for c in hits[:12]))


# ---------- 按发送者 ----------

def _decode(rows, key):
    from . import wx as _wx
    i2u = core._id2user()
    nm = core.names()
    me_ = core.me()
    out = []
    for lid, lt, ts, sid, content, ctype in rows:
        body = _wx.text_of(content, ctype) if content not in (None, "") else ""
        snd, body = _wx.split_sender(body)
        snd = snd or i2u.get(int(sid or 0), "")
        out.append({
            "id": int(lid), "ts": int(ts or 0), "type": core.label(lt),
            "from": "我" if snd == me_ else (nm.get(snd) or snd or "对方"),
            "sender": snd, "mine": snd == me_,
            "text": core.clean(body), "raw_len": len(body or ""),
        })
    return out


def sender_candidates(chat, name):
    """在会话里找名字匹配的发送者（先看最近的，再全表扫 rare 情况）。"""
    from . import wx as _wx
    key = core._key()
    t = chat["table"]
    rows = _wx.q(core._msgdb(), f"select distinct real_sender_id from {t}", key)
    ids = [int(r[0] or 0) for r in rows]
    i2u = core._id2user(); nm = core.names()
    hits = []
    for rid in ids:
        if rid <= 0:
            continue
        u = i2u.get(rid, "")
        disp = nm.get(u) or u
        if name in (disp or "") or name in (u or ""):
            hits.append((u, rid, disp))
    return hits


def fetch_by(chat, sender_ids, start=None, end=None, cap=20000):
    from . import wx as _wx
    key = core._key()
    t = chat["table"]
    cond = " or ".join(f"real_sender_id={i}" for i in sender_ids)
    where = [f"({cond})"]
    if start:
        where.append(f"create_time >= {int(start)}")
    if end:
        where.append(f"create_time <= {int(end)}")
    rows = _wx.q(core._msgdb(),
                 f"select local_id,local_type,create_time,real_sender_id,message_content,"
                 f"WCDB_CT_message_content from {t} where {' and '.join(where)} "
                 f"order by create_time limit {int(cap)}", key)
    return _decode(rows, key)


# ---------- 取数 ----------

def fetch(chat, start, end, limit=MAX_LIMIT):
    rows = core.messages(chat["username"], limit=limit)
    return [m for m in rows if start <= m["ts"] <= end]


CHAT_KIND = {"v": "person"}


def who_of(m):
    if m["mine"]:
        return "我"
    if CHAT_KIND["v"] == "person":
        return "对方"
    return m.get("from") or "对方"


def body_of(m):
    t = (m.get("text") or "").strip()
    return t or f"[{m['type']}]"


def fmt_ts(ts):
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def local_summary(chat, rows, start, end):
    if not rows:
        return "这段时间没有消息。"
    mine = [m for m in rows if m["mine"]]
    kinds = {}
    for m in rows:
        kinds[m["type"]] = kinds.get(m["type"], 0) + 1
    kstr = "、".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:5])
    days = {}
    for m in rows:
        d = time.strftime("%m-%d", time.localtime(m["ts"]))
        days[d] = days.get(d, 0) + 1
    top_days = sorted(days.items(), key=lambda x: -x[1])[:3]
    lines = [
        f"{chat['name']}（{chat['kind']}）",
        f"时间：{fmt_ts(start)} – {fmt_ts(end)}",
        f"共 {len(rows)} 条，我 {len(mine)} 条，对方 {len(rows) - len(mine)} 条",
        f"类型：{kstr}",
        f"最活跃：{ '、'.join(f'{d} {n}条' for d, n in top_days) }",
    ]
    tail = rows[-6:]
    lines.append("最后几句：")
    for m in tail:
        who = who_of(m)
        lines.append(f"  {fmt_ts(m['ts'])} {who}: {m['text'][:60]}")
    return "\n".join(lines)


def ai_summary(chat, rows, start, end, ask=""):
    if not rows:
        return "这段时间没有消息。"
    # 采样：均匀抽 220 条，保留首尾
    sample = rows
    if len(rows) > 90:
        step = len(rows) / 90
        idx = sorted({int(i * step) for i in range(90)} | {0, len(rows) - 1})
        sample = [rows[i] for i in idx]
    convo = []
    for m in sample:
        who = who_of(m)
        convo.append(f"[{fmt_ts(m['ts'])}] {who}: {m['text'][:200]}")
    prompt = (
        f"以下是「{chat['name']}」与我的聊天记录（{fmt_ts(start)} 到 {fmt_ts(end)}，"
        f"共 {len(rows)} 条，下面抽样 {len(sample)} 条）。\n\n"
        + "\n".join(convo)
        + "\n\n请用中文总结，要求：\n"
        "1. 先用一句话说这段时间主要在聊什么；\n"
        "2. 分 3-6 条要点，每条给具体事由、时间、关键数字（金额/时间/地点/名字）；\n"
        "3. 如果里面有需要我回应或还悬着的事，单列「待办 / 待回」；\n"
        "4. 不要复述无关寒暄，不要编造记录里没有的信息。"
        + (f"\n5. 特别回答这个问题：{ask}" if ask else "")
    )
    out = llm.chat(prompt, system="你是一个准确、克制的聊天记录整理助手。只依据给定记录。",
                   temperature=0.2, max_tokens=1600, fast=True)
    if not out:
        return local_summary(chat, rows, start, end) + "\n\n（模型没连上，以上是本地统计）"
    return out.strip()


def render_text(chat, rows, start, end, summary, show=12):
    lines = [f"【{chat['name']}】{fmt_ts(start)} – {fmt_ts(end)}  共 {len(rows)} 条", "", summary, ""]
    if rows:
        lines.append(f"—— 原文（最后 {min(show, len(rows))} 条）——")
        for m in rows[-show:]:
            who = who_of(m)
            lines.append(f"{fmt_ts(m['ts'])}  {who}: {m['text'][:120]}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", required=True)
    ap.add_argument("--by", default="", help="只列这个人发的消息")
    ap.add_argument("--from", dest="from_")
    ap.add_argument("--to")
    ap.add_argument("--days", type=int)
    ap.add_argument("--yesterday", action="store_true")
    ap.add_argument("--ask", default="")
    ap.add_argument("--limit", type=int, default=MAX_LIMIT)
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    chat = resolve(a.who)
    CHAT_KIND["v"] = chat["kind"]
    if a.by and not (a.from_ or a.days or a.yesterday):
        start, end = 0, now_ts()          # --by 默认查全部历史
    else:
        start, end = range_from_args(a)
    if a.by:
        cands = sender_candidates(chat, a.by)
        if not cands:
            raise SystemExit(f"会话「{chat['name']}」里没找到叫「{a.by}」的发送者")
        rows = fetch_by(chat, [c[1] for c in cands], start, end)
        who = "、".join(c[2] for c in cands)
        span = "全部" if not start else f"{fmt_ts(start)} – {fmt_ts(end)}"
        if a.json:
            print(json.dumps({"chat": chat["name"], "by": who, "count": len(rows),
                              "messages": [{"ts": m["ts"], "time": fmt_ts(m["ts"]), "type": m["type"],
                                            "text": body_of(m)} for m in rows]},
                             ensure_ascii=False, indent=2))
            return
        lines = [f"【{chat['name']}】{who} 的发言  {span}  共 {len(rows)} 条", ""]
        for m in rows:
            lines.append(f"{fmt_ts(m['ts'])}  [{m['type']}]  {body_of(m)}")
        if a.ask and not a.no_ai:
            print("\n".join(lines))
            print("\n—— 总结 ——")
            print(ai_summary(chat, rows, start, end, a.ask))
        else:
            print("\n".join(lines))
        return

    rows = fetch(chat, start, end, a.limit)
    summary = (local_summary(chat, rows, start, end) if a.no_ai
               else ai_summary(chat, rows, start, end, a.ask))
    if a.json:
        print(json.dumps({
            "chat": chat["name"], "kind": chat["kind"],
            "from": start, "to": end, "count": len(rows),
            "summary": summary,
            "messages": [{"ts": m["ts"], "time": fmt_ts(m["ts"]),
                          "who": who_of(m),
                          "type": m["type"], "text": body_of(m)[:500]} for m in rows[-a.show:]],
        }, ensure_ascii=False, indent=2))
    else:
        print(render_text(chat, rows, start, end, summary, a.show))


if __name__ == "__main__":
    main()
