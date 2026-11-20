#!/usr/bin/env python3
"""从导出的聊天记录里抽出「我」的语言风格画像。"""
import sqlite3, re, json, collections, statistics, datetime, pathlib, random

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE/"persona"; OUT.mkdir(exist_ok=True)
db = sqlite3.connect(HERE/"export/wechat.db"); db.row_factory = sqlite3.Row

chats = {r["username"]: dict(r) for r in db.execute("select * from chats")}
all_msgs = list(db.execute("select chat,ts,sender_name,direction,type,text from messages order by chat,ts"))

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")
PUNCT = "。！？!?，,、；;：:…~～"
TONE = "啊呀吧啦嘛哦噢嗯诶嘿哈哇耶咯咧嘞哒"
FILLER = ["哈哈","嘿嘿","嗯嗯","宝宝","宝儿","我的","可以","然后","就是","感觉","现在","看看","给你","我们","那你"]
ADDR = ["宝宝","宝儿","老婆","老公","兄弟","哥","姐","老师","同学","亲爱的","亲","宝","姐妹"]

def is_text(r): return r["type"] == "文本" and 0 < len(r["text"] or "") <= 200

groups = collections.defaultdict(list)
for r in all_msgs: groups[r["chat"]].append(r)

outs = [r for r in all_msgs if r["direction"] == "out" and is_text(r)]
lens = sorted(len(r["text"]) for r in outs)
stats = {}
stats["out_text_msgs"] = len(outs)
stats["len_mean"] = round(sum(lens)/len(lens), 2)
stats["len_median"] = lens[len(lens)//2]
stats["len_p90"] = lens[int(len(lens)*0.9)]
stats["len_max"] = lens[-1]
stats["no_punct_pct"] = round(sum(1 for r in outs if not re.search(r"[%s]" % re.escape(PUNCT), r["text"]))*100/len(outs), 1)
stats["emoji_pct"] = round(sum(1 for r in outs if EMOJI.search(r["text"]))*100/len(outs), 1)
stats["tone_pct"] = round(sum(1 for r in outs if re.search(r"[%s]" % TONE, r["text"]))*100/len(outs), 1)
stats["question_pct"] = round(sum(1 for r in outs if re.search(r"[?？]", r["text"]))*100/len(outs), 1)
stats["laugh_pct"] = round(sum(1 for r in outs if re.search(r"哈哈|嘿嘿|嘻嘻|hhh", r["text"]))*100/len(outs), 1)
stats["ascii_letter_pct"] = round(sum(1 for r in outs if re.search(r"[A-Za-z]", r["text"]))*100/len(outs), 1)
stats["punct_detail"] = {c: sum(1 for r in outs if c in r["text"]) for c in ["。","！","？","，","…","~","？"]}

# 连发段数 / 每段条数
bursts = []
for chat, rows in groups.items():
    last = 0; n = 0
    for r in rows:
        if r["direction"] == "out":
            if r["ts"] - last <= 60: n += 1
            else:
                if n: bursts.append((chat, n))
                n = 1
            last = r["ts"]
        else:
            if n: bursts.append((chat, n)); n = 0
            last = r["ts"]
    if n: bursts.append((chat, n))
bl = [n for _, n in bursts]
stats["turns"] = len(bl)
stats["msgs_per_turn_mean"] = round(sum(bl)/len(bl), 2)
stats["msgs_per_turn_dist"] = {k: sum(1 for x in bl if x == k) for k in range(1, 7)}
stats["multi_msg_turn_pct"] = round(sum(1 for x in bl if x >= 2)*100/len(bl), 1)

# 回复延迟
lat = []
for chat, rows in groups.items():
    prev_in = None
    for r in rows:
        if r["direction"] == "in" and r["type"] == "文本": prev_in = r["ts"]
        elif r["direction"] == "out" and prev_in:
            d = r["ts"] - prev_in
            if 0 <= d <= 3600: lat.append(d)
            prev_in = None
lat.sort()
if lat:
    stats["reply_latency_median_s"] = lat[len(lat)//2]
    stats["reply_latency_p90_s"] = lat[int(len(lat)*0.9)]
    stats["reply_within_60s_pct"] = round(sum(1 for x in lat if x <= 60)*100/len(lat), 1)

# 活跃时段
hours = collections.Counter(datetime.datetime.fromtimestamp(r["ts"]).hour for r in outs)
stats["active_hours_top"] = [h for h, _ in hours.most_common(6)]

# 高频短语
c = collections.Counter()
for r in outs:
    t = re.sub(r"[\s\W]+", "", r["text"])
    for n in (2, 3, 4):
        for i in range(len(t)-n+1): c[t[i:i+n]] += 1
stats["top_phrases"] = [[w, k] for w, k in c.most_common(80)]
stats["addr_terms"] = {w: sum(1 for r in outs if w in r["text"]) for w in ADDR}
stats["addr_terms"] = {k: v for k, v in sorted(stats["addr_terms"].items(), key=lambda x: -x[1]) if v}

# 私聊 vs 群聊
def prof(rs):
    if not rs: return {}
    ls = [len(r["text"]) for r in rs]
    return dict(n=len(rs), len=round(sum(ls)/len(ls), 1),
                punct=round(sum(1 for r in rs if not re.search(r"[%s]" % re.escape(PUNCT), r["text"]))*100/len(rs), 1),
                emoji=round(sum(1 for r in rs if EMOJI.search(r["text"]))*100/len(rs), 1),
                tone=round(sum(1 for r in rs if re.search(r"[%s]" % TONE, r["text"]))*100/len(rs), 1))
priv = [r for r in outs if not r["chat"].endswith("@chatroom")]
grp = [r for r in outs if r["chat"].endswith("@chatroom")]
stats["private_vs_group"] = {"private": prof(priv), "group": prof(grp)}

# 开头/结尾
first_of_day, last_of_day = [], []
for chat, rows in groups.items():
    day = None; buf = []
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"]).date()
        if d != day:
            if buf: last_of_day.append(buf[-1])
            buf = []; day = d
        buf.append(r)
    if buf: last_of_day.append(buf[-1])
for chat, rows in groups.items():
    cur = None
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"]).date()
        if d != cur and r["direction"] == "out":
            first_of_day.append(r["text"])
        cur = d
stats["openers"] = [t for t, _ in collections.Counter(first_of_day).most_common(15)]
stats["closers"] = [t for t, _ in collections.Counter([r["text"] for r in last_of_day if r["direction"] == "out"]).most_common(15)]

# 每个高频会话的风格差异
per_chat = []
for chat, rows in groups.items():
    rs = [r for r in rows if r["direction"] == "out" and is_text(r)]
    if len(rs) < 200: continue
    p = prof(rs)
    p["chat"] = chats.get(chat, {}).get("name", chat)
    p["kind"] = chats.get(chat, {}).get("kind", "")
    per_chat.append(p)
per_chat.sort(key=lambda x: -x["n"])
stats["per_chat"] = per_chat[:12]

json.dump(stats, open(OUT/"persona.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in stats.items() if k not in ("top_phrases","per_chat","openers","closers")}, ensure_ascii=False, indent=1))
print("TOP:", stats["top_phrases"][:25])
print("OPENERS:", stats["openers"][:8])
print("CLOSERS:", stats["closers"][:8])
