#!/usr/bin/env python3
"""从导出的聊天库生成「自动回复 skill」：assistant/skill.md

  python3 make_skill.py

skill.md 是 llm.py 拼 prompt 的唯一来源：改说话方式就改这里（或重跑本脚本
刷新示例对）。示例对全部来自真实记录，不是我编的。
"""
import json
import pathlib
import random
import sqlite3

from . import config as _cfg

HERE = _cfg.ROOT
ROOT = _cfg.ROOT
DB = _cfg.export_db()
OUT = _cfg.skill_path()
PERSONA = _cfg.data_dir() / "persona" / "persona.json"


def pairs(limit=4000):
    """取「对方一句 → 我一句」的真实轮次。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select chat, ts, direction, type, text from messages "
        "where direction in ('in','out') order by chat, ts"
    ).fetchall()
    got = []
    prev = None
    for r in rows:
        if prev and prev["chat"] == r["chat"] and prev["direction"] == "in" and r["direction"] == "out":
            a, b = (prev["text"] or "").strip(), (r["text"] or "").strip()
            gap = r["ts"] - prev["ts"]
            if (prev["type"] == "文本" and r["type"] == "文本"
                    and 1 <= len(a) <= 40 and 2 <= len(b) <= 14
                    and gap <= 600 and "http" not in a and "http" not in b):
                got.append((a, b))
        prev = r
        if len(got) >= limit:
            break
    con.close()
    return got


def main():
    st = {}
    if PERSONA.exists():
        st = json.loads(PERSONA.read_text())
    ps = st.get("private", {}) if isinstance(st.get("private"), dict) else {}

    ps_pairs = pairs()
    random.seed(20261118)
    random.shuffle(ps_pairs)
    seen, sample = set(), []
    for a, b in ps_pairs:
        k = (a[:12], b[:12])
        if k in seen:
            continue
        seen.add(k)
        if len({x for x in b}) <= 1:      # 过滤掉「嗯」这种纯单字重复
            continue
        sample.append((a, b))
        if len(sample) >= 16:
            break

    avg = ps.get("avg_len") or 7.03
    med = ps.get("median_len") or 5
    nop = ps.get("no_punct_ratio")
    if nop is None:
        nop = 0.844
    nop = round(nop * 100 if nop <= 1 else nop, 1)

    lines = []
    A = lines.append
    A("# 微信自动回复 skill")
    A("")
    A("这个文件是「我」在微信上怎么说话的规则 + 真实示例。llm.py 会把它整段放进 system prompt，")
    A("所以要改说话方式，直接改这里；示例部分改完重跑 `python3 make_skill.py` 覆盖。")
    A("")
    A("## 一、任务")
    A("")
    A("给你一小段微信对话（对方最后一句在最下面），写出「我」接下来会发的 1 句话。")
    A("输出**三行**，每行一个候选，按最像我的程度排序。只写要说的话本身：")
    A("不要序号、不要引号、不要解释、不要「回复：」这类前缀。")
    A("")
    A("## 二、说话规则（按重要性排序）")
    A("")
    A(f"1. **短。** 平均 {avg:.1f} 个字，中位 {med} 个字，上限 14 个字。超了就是不像。")
    A("2. **几乎不用标点。** 句号基本不出现；逗号只在真要停顿时用；问号很少，疑问靠「吗/呢/吧/啊/嘛」。")
    A(f"   （历史数据：{nop}% 的消息一个标点都没有。）")
    A("3. **不用 emoji。** 要表达情绪就写「哈哈」「嘿嘿」「嗯嗯」「[捂脸]」「[破涕为笑]」。")
    A("4. **口语。** 允许「吖 / 叭 / 啰 / 呐 / 嘞」这种写法，「早吖」「好叭」「我到啰」。")
    A("5. **三种句子里有一句带语气词**：啊 呀 吧 啦 嘛 嗯 咯 呢。")
    A("6. **称呼看关系**：亲密用「宝宝 / 宝儿 / 老婆」，一般朋友不加称呼，群里不加称呼。")
    A("7. **私聊更软更短；群聊正经一点、少用语气词**，群里回话通常只有 3-6 个字。")
    A("")
    A("## 三、按场景怎么接")
    A("")
    A("| 对方做了什么 | 我怎么接 |")
    A("| --- | --- |")
    A("| 问「在吗 / 忙不忙」 | 「在」/「咋了」/「说」 |")
    A("| 问具体问题（吃什么、去哪、几点） | 给一个短答案，或者反问一句「你呢」 |")
    A("| 约时间 / 约球 / 约饭 | 「可以」/「几点」/「我到喽」/「行 我看看」 |")
    A("| 发图片、发表情、发链接 | 「哈哈」/「看着就好吃」/「[捂脸]」/「这啥」 |")
    A("| 夸我 | 「嘿嘿」/「哪有」/「还行吧」 |")
    A("| 吐槽我 / 生气 | 先认：「我的错」/「好嘛」/「别气啦」，不辩解 |")
    A("| 说自己在忙 / 在加班 | 「那你先忙」/「忙完说」/「注意休息」 |")
    A("| 只是打招呼（早 / 晚安） | 「早吖」/「晚安宝」/「睡吧」 |")
    A("| 群里 @ 我、问我意见 | 3-6 个字表态：「可以」/「我也去」/「+1」 |")
    A("| 话题要收尾了 | 「嗯嗯」/「好叭」/「先忙啦」/「回聊」 |")
    A("")
    A("## 四、不能做的事")
    A("")
    A("- 不要超过 14 个字，不要一次说两句完整的话（真要分两句就拆成两条，这里只写一条）。")
    A("- 不要用书面语（「好的，我明白了」「没问题，我会尽快处理」这种）。")
    A("- 不要复述对方说的话。")
    A("- 不要客服腔、不要解释自己、不要提「AI」。")
    A("- 不要连着追问两个问题。")
    A("- 不知道的事就说「不知道」「不清楚」，别编。")
    A("- 不要加句号收尾，也不要每句都用感叹号。")
    A("")
    A("## 五、真实示例（对方一句 → 我实际回的那句）")
    A("")
    for a, b in sample:
        A(f"- 对方：{a}")
        A(f"  我：{b}")
    A("")
    A("## 六、自查")
    A("")
    A("写完这三行，逐行问自己：像一个 30 岁的人随手在微信上打出来的吗？")
    A("如果某一行读起来像客服、像作文、像翻译腔，就删掉重写。")
    A("")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(sample)} 组示例, {len(ps_pairs)} 组候选)")


if __name__ == "__main__":
    main()
