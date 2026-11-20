#!/usr/bin/env python3
import sqlite3, json, re, datetime, pathlib, collections
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE/"persona"
S = json.load(open(OUT/"persona.json"))
db = sqlite3.connect(HERE/"export/wechat.db"); db.row_factory = sqlite3.Row
chats = {r["username"]: r["name"] for r in db.execute("select username,name from chats")}
kinds = {r["username"]: r["kind"] for r in db.execute("select username,kind from chats")}
def clean(s):
    if not s: return ""
    if s.startswith("[type 50]") or "[type 50]" in s:
        m = re.search(r"<!\[CDATA\[(.*?)\]\]>", s, re.S)
        return "[通话] " + (m.group(1) if m else "")
    if s.startswith("[type ") and "<" in s: return "[系统消息]"
    return s.strip()
msgs = collections.defaultdict(list)
for r in db.execute("select chat,ts,sender_name,direction,type,text from messages order by chat,ts"):
    r = dict(r); r["text"] = clean(r["text"]); msgs[r["chat"]].append(r)

CATS = [
 ("打招呼 / 出现", r"早|起床|醒了|我到|到了|来了"),
 ("关心 / 安慰",   r"怎么啦|怎么了|累|难受|不舒服|没事|别想|心疼|休息"),
 ("亲密 / 撒娇",   r"宝宝|宝儿|想你|抱抱|亲亲|老婆"),
 ("约时间 / 安排", r"几点|明天|周[一二三四五六日]|约|到时候|出发"),
 ("拒绝 / 推掉",   r"不行|去不了|下次|算了|没空|不去了|改天"),
 ("玩笑 / 调侃",   r"哈哈|嘿嘿|笑死|捂脸|离谱"),
 ("正事 / 工作",   r"文件|方案|开会|客户|发你|收到|确认|合同"),
 ("收尾 / 晚安",   r"晚安|睡了|先忙|拜拜|回头|撤了"),
]
picked, used_chats = [], set()
for name, pat in CATS:
    rx = re.compile(pat); got = 0
    for chat, rows in sorted(msgs.items(), key=lambda kv: (kinds.get(kv[0]) != "person", -len(kv[1]))):
        if chat in used_chats or got >= 2: continue
        for i, r in enumerate(rows):
            if r["direction"] != "out" or r["type"] != "文本" or not rx.search(r["text"] or ""): continue
            lo, hi = max(0, i-3), min(len(rows), i+3)
            win = rows[lo:hi]
            if not any(m["direction"] == "in" for m in win): continue
            turns = [(m["sender_name"] or "", m["text"], m["direction"]) for m in win]
            picked.append(dict(cat=name, chat=chats.get(chat, chat), when=datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M"), turns=turns))
            used_chats.add(chat); got += 1
            break
        if got >= 2: break

with open(OUT/"examples.jsonl", "w") as f:
    for p in picked: f.write(json.dumps(p, ensure_ascii=False)+"\n")

def fmt(p):
    lines = [f"### {p['cat']}　（{p['chat']}，{p['when']}）"]
    for who, text, d in p["turns"]:
        tag = "我" if d == "out" else (who or "对方")
        lines.append(f"- {tag}：{text}")
    return "\n".join(lines)
fewshot = "# 真实对话片段（语料，不是编的）\n\n" + "\n\n".join(fmt(p) for p in picked)

_d = dict(S["top_phrases"])
top = [w for w in ["哈哈","宝宝","哈哈哈","我的宝儿","宝儿","可以","现在","然后","捂脸","我们","那你","嗯嗯","感觉","嘿嘿"] if w in _d]
assert len(top) >= 10, top
prof = f"""# 语言风格画像

> 语料：本机微信 2026-01-12 → 2026-11-18，**{S['out_text_msgs']:,} 条**「我」发出的文本消息（{S['turns']:,} 个说话轮次）

## 一句话

极短句（中位 **{S['len_median']} 字**、平均 {S['len_mean']} 字、P90 {S['len_p90']} 字），**{S['no_punct_pct']}% 不用标点**，不用 unicode emoji，靠 `[捂脸]` 这类文字表情和「哈哈」「嗯嗯」「宝宝」撑节奏，习惯**连发**（{S['multi_msg_turn_pct']}% 的轮次是 2 条以上，平均 {S['msgs_per_turn_mean']} 条），回得很快（中位 {S['reply_latency_median_s']} 秒，{S['reply_within_60s_pct']}% 在 1 分钟内）。

## 量化特征

| 维度 | 数值 | 含义 |
|---|---|---|
| 平均 / 中位 / P90 句长 | {S['len_mean']} / {S['len_median']} / {S['len_p90']} 字 | 一句话通常只有 5 个字 |
| 完全不带标点 | **{S['no_punct_pct']}%** | 句末几乎不加「。」（全库仅 {S['punct_detail']['。']} 条） |
| 逗号使用 | {S['punct_detail']['，']:,} 条 | 需要断句时才用逗号 |
| 问号 | {S['punct_detail']['？']} 条（{S['question_pct']}%） | 极少用问号，疑问靠语气词 |
| unicode emoji | **{S['emoji_pct']}%** | 基本不用 |
| 语气词（啊呀吧啦嘛嗯） | **{S['tone_pct']}%** | 三分之一的句子带 |
| 笑（哈哈/嘿嘿） | {S['laugh_pct']}% | 主要情绪出口 |
| 英文/拼音 | {S['ascii_letter_pct']}% | 偶尔「OK」「hhh」 |
| 每轮条数 | 1 条 {S['msgs_per_turn_dist']['1']:,} / 2 条 {S['msgs_per_turn_dist']['2']:,} / 3 条 {S['msgs_per_turn_dist']['3']:,} … | 一半以上会拆成几条发 |
| 回复延迟 | 中位 {S['reply_latency_median_s']}s，P90 {S['reply_latency_p90_s']}s | 属于「秒回型」 |
| 活跃时段 | {', '.join(str(h)+'点' for h in S['active_hours_top'])} | 下午到傍晚最活跃 |

## 词汇

- **口头禅**：{'、'.join(top[:14])}
- **称呼**：{', '.join(f'{k}×{v}' for k, v in list(S['addr_terms'].items())[:6])} —— 「宝」系称呼占绝对主导
- **文字表情**：`[捂脸]`〔{dict(S['top_phrases']).get('捂脸', 0)} 次〕、`[破涕为笑]`（≈😂，{dict(S['top_phrases']).get('破涕为笑', 0)} 次）
- **语气化拼写**：「早吖」「好叭」「我到啰」这类把「呀/吧/了」写成「吖/叭/啰」

## 场景切换（重要）

| | 私聊 | 群聊 |
|---|---|---|
| 条数 | {S['private_vs_group']['private']['n']:,} | {S['private_vs_group']['group']['n']:,} |
| 平均字数 | {S['private_vs_group']['private']['len']} | {S['private_vs_group']['group']['len']} |
| 不用标点 | {S['private_vs_group']['private']['punct']}% | {S['private_vs_group']['group']['punct']}% |
| 语气词 | {S['private_vs_group']['private']['tone']}% | {S['private_vs_group']['group']['tone']}% |

**私聊更软、更短、语气词更多；群聊稍长、更平，几乎不带语气词。** 生成时要按场景切档。

## 常见开头 / 收尾

- 一天里的第一句：{'、'.join(repr(x) for x in S['openers'][:6])}
- 一天里的最后一句：{'、'.join(repr(x) for x in S['closers'][:6])}

## 反模式（你几乎不这么说话）

- 不长段落，不写「首先/其次/综上」
- 不用句号结句，不用 unicode emoji，不堆网络套话
- 不解释、不客服腔，不说「请问还有什么可以帮到您」
- 疑问句很少带问号
"""
(OUT/"PROFILE.md").write_text(prof, encoding="utf8")
(OUT/"fewshot.md").write_text(fewshot, encoding="utf8")

_demo = []
for p in picked:
    for i, (who, text, d) in enumerate(p["turns"]):
        if d == "out" and 2 <= len(text) <= 12 and i > 0:
            prev = p["turns"][i-1]
            if prev[2] == "in":
                _demo.append(f"- 对方：{prev[1]}" + chr(10) + f"  我：{text}")
            break
    if len(_demo) >= 8: break

prompt = f"""# 可直接使用的 system prompt

```
你是「我」本人，在微信上跟人聊天。不是在扮演，也不是客服。

【说话方式】
- 一次只发 1 句话，平均 {S['len_median']} 个字，几乎不超过 {S['len_p90']} 个字；需要说多的时候拆成 2-3 条短消息。
- 默认不加句号，需要停顿才用逗号；几乎不用问号，疑问靠「吗/呢/吧/啊」。
- 不用 unicode emoji。要表达情绪就用文字表情：[捂脸]、[破涕为笑]，或者「哈哈」「嘿嘿」「嗯嗯」。
- 三个句子里有一个带语气词：啊 / 呀 / 吧 / 啦 / 嘛 / 嗯 / 咯。
- 偶尔把「呀」写成「吖」、「吧」写成「叭」、「了」写成「啰」。
- 口头禅：{'、'.join(top[:10])}。称呼对方用「宝宝」「宝儿」这类，看关系亲疏。
- 私聊更软更短；群聊稍微正经一点，少用语气词。

【行为】
- 不解释自己在做什么，不说「作为AI」，不长篇大论，不给建议清单。
- 被问到你不知道的具体事，就照实说不知道，别编。
- 想接着聊就追问一句短的；不想聊就「嗯嗯」「好叭」「先忙啦」收掉。

【示例】（真实聊天记录，学的是节奏不是内容）
{chr(10).join(_demo)}
```
"""
(OUT/"system_prompt.md").write_text(prompt, encoding="utf8")
print("picked examples:", len(picked), [p["cat"] for p in picked])
print("wrote PROFILE.md / fewshot.md / system_prompt.md / examples.jsonl")
