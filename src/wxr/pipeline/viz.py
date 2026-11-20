#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 persona.json 的统计变成一张编辑风格的静态页面：persona/index.html"""
import json, sqlite3, html, os, datetime, collections, statistics

from .. import config as _cfg

HERE = str(_cfg.data_dir()/"persona")
ROOT = str(_cfg.ROOT)
DB = str(_cfg.export_db())

P = json.load(open(os.path.join(HERE, "persona.json"), encoding="utf-8"))

con = sqlite3.connect(DB)
cur = con.cursor()

# ---------- 数据 ----------
rows = cur.execute(
    "select ts, text from messages where direction='out' and type='文本' and text<>''"
).fetchall()

LEN_BUCKETS = [(1, 2), (3, 4), (5, 7), (8, 10), (11, 14), (15, 20), (21, 30), (31, 999)]
len_hist = []
for lo, hi in LEN_BUCKETS:
    n = sum(1 for _, t in rows if lo <= len(t) <= hi)
    label = f"{lo}" if lo == hi else (f"{lo}+" if hi == 999 else f"{lo}–{hi}")
    len_hist.append((label, n))
len_hist_total = sum(n for _, n in len_hist)
N = len(rows)
_lmax = max(n for _, n in len_hist)
LEN_ROWS = "".join(
    f'<li><b>{lab}</b><span class="t"><span style="width:{n/_lmax*100:.1f}%"></span></span><i>{n:,}</i></li>'
    for lab, n in len_hist
)

# 小时 × 星期 热力
hw = [[0] * 24 for _ in range(7)]
for ts, _ in rows:
    d = datetime.datetime.fromtimestamp(ts)
    hw[d.weekday()][d.hour] += 1
hw_max = max(max(r) for r in hw)

# 回复延迟（对方一句 -> 我第一句）
lat = []
by_chat = collections.defaultdict(list)
for chat, ts, direction in cur.execute(
    "select chat, ts, direction from messages where type in ('文本','表情','图片','应用消息') order by chat, ts"
):
    by_chat[chat].append((ts, direction))
for seq in by_chat.values():
    prev_in = None
    for ts, direction in seq:
        if direction == "in":
            if prev_in is None:
                prev_in = ts
        elif prev_in is not None:
            gap = ts - prev_in
            if 0 <= gap <= 60 * 60 * 24:
                lat.append(gap)
            prev_in = None
lat.sort()


def pct(arr, p):
    if not arr:
        return 0
    k = min(len(arr) - 1, int(round((len(arr) - 1) * p)))
    return arr[k]


lat_median, lat_p90 = pct(lat, 0.5), pct(lat, 0.9)
lat_60 = round(sum(1 for x in lat if x <= 60) / max(len(lat), 1) * 100, 1)
lat_fast = sum(1 for x in lat if 3 <= x <= 30) / max(len(lat), 1) * 100

# 标点
pd = P["punct_detail"]
punct_total_msgs = P["out_text_msgs"]

# 口头禅
phrases = [kv for kv in P["top_phrases"]
           if not (kv[0].startswith("的") or kv[0].startswith("我的"))][:12]
addr = sorted(P["addr_terms"].items(), key=lambda kv: -kv[1])
pv, gp = P["private_vs_group"]["private"], P["private_vs_group"]["group"]

# 例子
examples = []
with open(os.path.join(HERE, "examples.jsonl"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            examples.append(json.loads(line))
def ex_score(e):
    outs = [t for _, t, d in e["turns"] if d == "out"]
    return sum(1 for t in outs if 1 <= len(t) <= 14) - sum(1 for t in outs if len(t) > 16)

ranked = sorted(examples, key=ex_score, reverse=True)
pick, seen_cat = [], set()
for e in ranked:
    if e["cat"] in seen_cat:
        continue
    seen_cat.add(e["cat"])
    pick.append(e)
    if len(pick) == 2:
        break

TODAY = datetime.date.today().isoformat()
SECTIONS = ["概览","句长","标点","节奏","速度","作息","口头禅","称呼","场合","原文","反模式"]
INDEX = "".join(
    f'<a href="#s{i+1:02d}"><b>{i+1:02d}</b>{t}</a>' for i, t in enumerate(SECTIONS)
)

# ---------- 小工具 ----------
def esc(s):
    return html.escape(s, quote=True)


def fmt(n):
    return f"{n:,}"

# ---------- SVG: 句长 ----------
def svg_len_hist():
    w, rowh, gap, left, right = 660, 26, 8, 56, 76
    h = len(len_hist) * (rowh + gap) + 28
    mx = max(n for _, n in len_hist)
    bars = []
    for i, (label, n) in enumerate(len_hist):
        y = 10 + i * (rowh + gap)
        bw = (n / mx) * (w - left - right)
        bars.append(
            f'<g><text x="{left-12}" y="{y+rowh*0.7}" text-anchor="end" class="tick">{label}</text>'
            f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{rowh}" rx="1" class="bar"/>'
            f'<text x="{left+bw+10:.1f}" y="{y+rowh*0.7}" class="val">{fmt(n)}</text></g>'
        )
    # 中位线
    target = 5
    acc = 0
    for i, (label, n) in enumerate(len_hist):
        lo = int(label.split("–")[0].replace("+", ""))
        hi = int(label.split("–")[-1]) if "–" in label else lo
        if lo <= target <= hi:
            y = 10 + i * (rowh + gap) + rowh + gap / 2
            bars.append(
                f'<line x1="{left}" x2="{w-right}" y1="{y}" y2="{y}" class="mark"/>'
                f'<text x="{w-right+4}" y="{y+4}" class="mark-t">中位 5</text>'
            )
            break
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="句长分布">{"".join(bars)}</svg>'


# ---------- SVG: 热力 ----------
def svg_heatmap():
    cell, gapx, left, top = 22, 4, 34, 20
    w = left + 24 * (cell + gapx) + 8
    h = top + 7 * (cell + gapx) + 30
    days = ["一", "二", "三", "四", "五", "六", "日"]
    out = []
    for r in range(7):
        out.append(f'<text x="{left-10}" y="{top + r*(cell+gapx) + cell*0.72}" text-anchor="end" class="tick">{days[r]}</text>')
        for c in range(24):
            v = hw[r][c]
            a = (v / hw_max) ** 0.6 if hw_max else 0
            out.append(
                f'<rect x="{left + c*(cell+gapx)}" y="{top + r*(cell+gapx)}" width="{cell}" height="{cell}" rx="1.5" '
                f'fill="var(--accent)" fill-opacity="{0.06 + 0.94*a:.3f}"><title>{days[r]} {c:02d}:00 — {v} 条</title></rect>'
            )
    for c in range(0, 24, 3):
        out.append(f'<text x="{left + c*(cell+gapx) + cell/2}" y="{h-10}" text-anchor="middle" class="tick">{c}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart heat" role="img" aria-label="一周内每小时发送量">{"".join(out)}</svg>'


peak = max(((hw[r][h], r, h) for r in range(7) for h in range(24)))
PEAK_TXT = f"周{'一二三四五六日'[peak[1]]} {peak[2]:02d}:00 · {fmt(peak[0])} 条"

# ---------- SVG: 连发节奏 ----------
def svg_burst():
    dist = P["msgs_per_turn_dist"]
    keys = ["1", "2", "3", "4", "5", "6"]
    total = sum(dist.values())
    w, h, bar_y, bar_h = 900, 76, 8, 30
    x = 0
    segs, labels, legend = [], [], []
    shades = [0.16, 0.30, 0.45, 0.60, 0.78, 1.0]
    for k, sh in zip(keys, shades):
        v = dist[k]
        bw = w * v / total
        segs.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{max(bw-1.5,0.6):.1f}" height="{bar_h}" fill="var(--accent)" fill-opacity="{sh}" rx="1">'
            f'<title>{k} 条：{fmt(v)} 轮</title></rect>'
        )
        legend.append(f'<li><b>{k} 条</b><i>{v/total*100:.1f}%</i></li>')
        x += bw
    return f'<svg viewBox="0 0 {w} {bar_h+12}" class="chart strip" role="img" aria-label="每轮消息条数">{"".join(segs)}</svg>', "".join(legend)


# ---------- SVG: 延迟轴 ----------
def svg_latency():
    import math
    edges = [0, 1, 3, 10, 30, 60, 180, 600, 3600, 21600, 86401]
    import bisect
    cnt = [0] * (len(edges) - 1)
    for g in lat:
        cnt[bisect.bisect_right(edges, g) - 1] += 1
    w = 880
    x0, x1, base, top = 40, 840, 104, 34
    h = 132
    lg = math.log10(86400)

    def X(v):
        return x0 + (math.log10(max(v, 1)) / lg) * (x1 - x0)

    mx = max(cnt)
    bars, extra = [], []
    for i, n in enumerate(cnt):
        lo, hi = edges[i], edges[i + 1]
        bh = (n / mx) * (base - top)
        bx = X(lo) + (1.5 if lo else 0)
        bw = max(X(hi) - X(lo) - 2.2, 1.2)
        bars.append(
            f'<rect x="{bx:.1f}" y="{base-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" class="bar"/>'
            f'<title>{lo}–{hi}s：{fmt(n)} 次</title>'
        )
        if n == mx:
            extra.append(
                f'<text x="{bx+bw/2:.1f}" y="{base-bh-9:.1f}" text-anchor="middle" class="val">'
                f'{n/len(lat)*100:.0f}%</text>'
            )
    ticks = [(1, "1s"), (10, "10s"), (60, "1分"), (600, "10分"), (3600, "1时"), (21600, "6时"), (86400, "1天")]
    ax = [f'<line x1="{x0}" x2="{x1}" y1="{base}" y2="{base}" class="axis"/>']
    for v, lab in ticks:
        ax.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{base}" y2="{base+5}" class="axis"/>')
        ax.append(f'<text x="{X(v):.1f}" y="{base+20}" text-anchor="middle" class="tick">{lab}</text>')
    for v, lab in [(lat_median, f"中位 {lat_median}s"), (lat_p90, f"P90 {lat_p90}s")]:
        ax.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{top-6}" y2="{base}" class="mark"/>')
        ax.append(f'<text x="{X(v):.1f}" y="{top-12}" text-anchor="middle" class="mark-t">{lab}</text>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="回复延迟分布">{"".join(bars)}{"".join(ax)}{"".join(extra)}</svg>'


# ---------- HTML ----------
phr = "".join(
    f'<li style="--s:{max(1.0, min(3.2, (c/520)**0.55)):.2f}"><b>{esc(p)}</b><i>{fmt(c)}</i></li>'
    for p, c in phrases
)

addr_rows = "".join(
    f'<tr><th>{esc(k)}</th><td class="num">{fmt(v)}</td>'
    f'<td><span class="mini" style="width:{v/addr[0][1]*100:.1f}%"></span></td></tr>'
    for k, v in addr[:7]
)

punct_sorted = sorted(pd.items(), key=lambda kv: -kv[1])
pmax = punct_sorted[0][1]
punct_rows = "".join(
    f'<tr><th>{esc(k)}</th>'
    f'<td class="track"><span style="width:{max(v/pmax*100, 1.2):.2f}%"></span></td>'
    f'<td class="num">{fmt(v)}</td>'
    f'<td class="num dim">{v/N*100:.2f}%</td></tr>'
    for k, v in punct_sorted
)


def example_block(e):
    lines = []
    for who, text, d in e["turns"][:9]:
        cls = "out" if d == "out" else "in"
        nm = "我" if d == "out" else "对方"
        lines.append(f'<div class="turn {cls}"><div class="who">{nm}</div><div class="says">{esc(text)}</div></div>')
    return (
        f'<figure class="slice"><figcaption>{esc(e["cat"])} · {esc(e["chat"])} · {esc(e["when"][:10])}</figcaption>'
        f'{"".join(lines)}</figure>'
    )


slices = "".join(example_block(e) for e in pick)

HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>语言指纹 · {fmt(N)} 条自我观察</title>
<style>
:root{{
  --paper:#F4F1E9; --paper-2:#EDE8DB; --ink:#17150F; --ink-2:#4B4639; --ink-3:#6B6553;
  --rule:#D8D1BF; --accent:#C0432B;
  --serif:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif;
  --mono:"SF Mono",ui-monospace,Menlo,monospace;
}}
*{{box-sizing:border-box}}
html{{background:var(--paper)}}
body{{
  margin:0;color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.75;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='.035'/%3E%3C/svg%3E");
  -webkit-font-smoothing:antialiased;
}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 40px}}
.num,.tick,.val,.mark-t{{font-family:var(--mono);font-variant-numeric:tabular-nums}}

/* 报头 */
header{{padding:44px 0 26px;border-bottom:1px solid var(--ink)}}
.kicker{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}}
h1{{font-family:var(--serif);font-weight:600;font-size:clamp(44px,7.4vw,88px);line-height:.98;letter-spacing:-.03em;margin:26px 0 14px}}
h1 em{{font-style:normal;color:var(--accent)}}
.standfirst{{font-family:var(--serif);font-size:clamp(17px,2.1vw,21px);line-height:1.72;max-width:34em;color:var(--ink-2);margin:0 0 26px}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 28px;font-family:var(--mono);font-size:11.5px;color:var(--ink-3);letter-spacing:.04em}}
.meta b{{color:var(--ink);font-weight:500}}

/* 目录 */
.index{{display:flex;flex-wrap:wrap;margin:26px 0 0}}
.index a{{font-family:var(--mono);font-size:11px;letter-spacing:.02em;color:var(--ink-3);text-decoration:none;padding:0 15px 0 0;margin:0 15px 6px 0;border-right:1px solid var(--rule);transition:color .12s}}
.index a:last-child{{border-right:0}}
.index a b{{color:var(--ink);font-weight:500;margin-right:7px}}
.index a:hover,.index a:focus-visible{{color:var(--accent)}}
.index a:focus-visible{{outline:1px solid var(--accent);outline-offset:2px}}

/* 章节 */
section{{display:grid;grid-template-columns:96px minmax(0,1fr);gap:0 32px;padding:54px 0;border-bottom:1px solid var(--rule)}}
section:last-of-type{{border-bottom:0}}
.no{{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.1em;padding-top:9px}}
h2{{font-family:var(--serif);font-weight:600;font-size:clamp(24px,3vw,33px);line-height:1.22;letter-spacing:-.01em;margin:0 0 10px}}
.lede{{color:var(--ink-2);max-width:36em;margin:0 0 30px}}
.lede b{{color:var(--ink);font-weight:600;background:linear-gradient(transparent 62%,rgba(192,67,43,.22) 62%)}}

/* 大数字 */
.figures{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--rule);border-block:1px solid var(--rule)}}
.figures div{{background:var(--paper);padding:22px 18px 20px}}
.figures b{{display:block;font-family:var(--mono);font-size:clamp(26px,3.4vw,38px);font-weight:500;letter-spacing:-.03em;line-height:1}}
.figures span{{display:block;margin-top:9px;font-size:12px;color:var(--ink-3);letter-spacing:.06em}}

/* 图表 */
.chart{{width:100%;height:auto;overflow:visible}}
.bar{{fill:var(--accent);fill-opacity:.82}}
.axis{{stroke:var(--ink-3);stroke-width:1}}
.mark{{stroke:var(--ink-2);stroke-width:1;stroke-dasharray:2 3}}
.dot{{fill:var(--accent)}}
.tick{{font-size:10.5px;fill:var(--ink-3);letter-spacing:.03em}}
.val{{font-size:11.5px;fill:var(--ink-2)}}
.mark-t{{font-size:10.5px;fill:var(--ink-2)}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:32px}}
.note{{font-size:12.5px;color:var(--ink-3);margin-top:14px;line-height:1.6}}
.note b{{color:var(--ink-2)}}

/* 表格 */
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{text-align:left;padding:9px 0;border-bottom:1px solid var(--rule);font-weight:400}}
th{{font-weight:500;width:6em}}
td.num{{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;padding-right:14px;width:6em}}
.dim{{color:var(--ink-3)}}
.mini{{display:block;height:6px;background:var(--accent);opacity:.55;min-width:2px}}

/* 句长条 */
.lenhist{{list-style:none;margin:14px 0 0;padding:0}}
.lenhist li{{display:grid;grid-template-columns:4.4em minmax(0,1fr) 6em;gap:16px;align-items:center;padding:5px 0}}
.lenhist b{{font-family:var(--mono);font-size:11.5px;font-weight:400;color:var(--ink-2)}}
.lenhist .t span{{display:block;height:15px;background:var(--accent);opacity:.82}}
.lenhist i{{font-family:var(--mono);font-style:normal;font-size:11.5px;color:var(--ink-2);text-align:right}}

/* 标点表 */
table.punct th{{width:2.6em;font-family:var(--serif);font-size:19px;font-weight:600;line-height:1.2;padding:7px 0}}
table.punct td.track{{padding:0 18px 0 6px;width:auto}}
table.punct td.track span{{display:block;height:7px;background:var(--accent);opacity:.75;min-width:2px}}
table.punct td.num{{width:5.4em}}
table.punct tr:last-child th,table.punct tr:last-child td{{border-bottom:0}}

/* 对比表 */
table.cmp tr>*{{width:6.6em}}
table.cmp tr>*:last-child{{width:auto;padding-left:30px}}
table.cmp thead th{{font-size:11px;letter-spacing:.08em;color:var(--ink-3);padding:0 0 6px}}
table.cmp thead th:first-child{{color:transparent}}
table.cmp td.num,table.cmp th.num{{text-align:right;padding-right:18px}}
table.cmp td:last-child{{color:var(--ink-3);font-size:12.5px;text-align:left}}

/* 连发图例 */
.strip{{width:100%;height:40px;display:block}}
.legend{{list-style:none;display:flex;flex-wrap:wrap;padding:0;margin:12px 0 0;border-top:1px solid var(--rule)}}
.legend li{{display:flex;align-items:baseline;gap:9px;padding:9px 20px 0 0;margin-right:20px;border-right:1px solid var(--rule)}}
.legend li:last-child{{border-right:0;margin-right:0;padding-right:0}}
.legend b{{font-weight:500;font-size:11.5px;color:var(--ink-2);letter-spacing:.02em}}
.legend i{{font-family:var(--mono);font-style:normal;font-size:11px;color:var(--ink-3)}}

/* 口头禅 */
.phrases{{list-style:none;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;padding:0;margin:0}}
.phrases li{{display:flex;align-items:baseline;gap:6px}}
.phrases b{{font-family:var(--serif);font-size:calc(15px * var(--s));font-weight:600;line-height:1.1}}
.phrases i{{font-family:var(--mono);font-style:normal;font-size:10.5px;color:var(--ink-3)}}

/* 对话切片 */
.slice{{margin:0;padding:22px 22px 8px;background:var(--paper-2);border:1px solid var(--rule)}}
.slice figcaption{{font-family:var(--mono);font-size:10.5px;color:var(--ink-3);letter-spacing:.04em;margin-bottom:16px;text-transform:uppercase}}
.turn{{display:grid;grid-template-columns:76px minmax(0,1fr);gap:12px;padding:5px 0;align-items:start}}
.turn .who{{font-size:11px;color:var(--ink-3);text-align:right;line-height:1.9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.turn .says{{font-size:14px;line-height:1.65}}
.turn.out .says{{display:inline-block;padding:4px 11px;background:#DDE8CB;border-radius:3px;justify-self:start}}
.turn.in .says{{display:inline-block;padding:4px 11px;background:#fff;border:1px solid var(--rule);border-radius:3px;justify-self:start}}
.turn .says + .says{{margin-top:2px}}

/* 引用/反模式 */
.pull{{font-family:var(--serif);font-size:clamp(20px,2.7vw,27px);line-height:1.55;margin:0 0 26px;padding-left:22px;border-left:2px solid var(--accent)}}
.dont{{list-style:none;padding:0;margin:0;display:grid;gap:12px}}
.dont li{{display:grid;grid-template-columns:18px 1fr;gap:10px;color:var(--ink-2);font-size:14px}}
.dont li::before{{content:"×";color:var(--accent);font-family:var(--mono);font-size:15px;line-height:1.5}}
footer{{padding:40px 0 70px;font-size:12px;color:var(--ink-3);line-height:1.8}}
footer code{{font-family:var(--mono);font-size:11.5px;background:var(--paper-2);padding:1px 5px}}

@media(max-width:860px){{
  .wrap{{padding:0 22px}}
  section{{grid-template-columns:1fr;gap:0;padding:40px 0}}
  .no{{padding:0 0 8px}}
  .figures{{grid-template-columns:1fr 1fr}}
  .grid2{{grid-template-columns:1fr;gap:26px}}
  .turn{{grid-template-columns:58px minmax(0,1fr)}}
}}
@media print{{
  body{{background:#fff;background-image:none}}
  .index{{display:none}}
  section{{break-inside:avoid;padding:28px 0}}
  .slice{{background:#fff}}
}}

@media(prefers-reduced-motion:no-preference){{
  .bar,.mini{{animation:none}}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="kicker"><span>本地数据 · 自我观察</span><span>Vol. 01 / {TODAY}</span></div>
  <h1>语言<em>指纹</em></h1>
  <p class="standfirst">把一个人自己发出去的 {fmt(N)} 条微信文本拆开看：句子有多短、标点去哪了、什么时候会连着发、多久回一句。这不是性格测试，是统计。</p>
  <div class="meta">
    <span>语料 <b>2026-01-12 → 2026-11-18</b></span>
    <span>账号 <b>{_cfg.account()}</b></span>
    <span>样本 <b>{fmt(N)} 条 · {fmt(P['turns'])} 轮</b></span>
    <span>口径 <b>只算我自己发的纯文本</b></span>
  </div>
  <nav class="index">{INDEX}</nav>
</header>

<section>
  <div class="no">01 — 概览</div>
  <div>
    <div class="figures">
      <div><b>{fmt(N)}</b><span>条我发的文本</span></div>
      <div><b>{P['len_mean']}</b><span>平均字数</span></div>
      <div><b>{P['no_punct_pct']}%</b><span>完全不带标点</span></div>
      <div><b>{P['msgs_per_turn_mean']}</b><span>每轮条数</span></div>
    </div>
    <p class="note">平均 {P['len_mean']} 字、中位 {P['len_median']} 字，意味着<b>一半的消息不超过 5 个字</b>。而 {P['no_punct_pct']}% 的消息里连一个标点都没有——不是不会打，是懒得打。</p>
  </div>
</section>

<section>
  <div class="no">02 — 句长</div>
  <div>
    <h2>字数是稀缺资源</h2>
    <p class="lede">把每条消息的字数分桶，形状是陡峭的单峰：<b>3–4 字最多</b>，越往后掉得越快。P90 只有 {P['len_p90']} 字，最长的一条 {fmt(P['len_max'])} 字——那是例外，不是风格。</p>
    <ul class="lenhist">{LEN_ROWS}</ul>
    <p class="note">横条长度＝该区间的消息条数，共 {fmt(len_hist_total)} 条。中位数 5 字落在 5–7 这一档的起点。</p>
  </div>
</section>

<section>
  <div class="no">03 — 标点</div>
  <div>
    <h2>句号几乎灭绝</h2>
    <p class="lede">整个语料里，我打过的句号只有 <b>{pd.get('。',0)} 个</b>，逗号 {fmt(pd.get('，',0))} 个，问号 {pd.get('？',0)} 个。问号少不代表不问，是靠语气词和语序在问。</p>
    <div class="grid2">
      <table class="punct">
        <tbody>{punct_rows}</tbody>
      </table>
      <div>
        <p class="note" style="margin-top:0">最右列是<b>占全部消息的比例</b>。逗号落在 {pd.get('，',0)/N*100:.1f}% 的消息里，句号只有 {pd.get('。',0)/N*100:.2f}%——相差约 {pd.get('，',1)//max(pd.get('。',1),1)} 倍。</p>
        <p class="note">功效上等价的做法是：用换行、空格、语气词（啊/嘛/吖/叭）和连发来断句。这也解释了为什么平均每条只有 {P['len_mean']} 字。</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="no">04 — 节奏</div>
  <div>
    <h2>一句话拆成几条发</h2>
    <p class="lede">把相邻 2 分钟内的连续发送算作一轮：<b>{P['multi_msg_turn_pct']}% 的轮次不止一条</b>，平均每轮 {P['msgs_per_turn_mean']} 条。</p>
    {svg_burst()[0]}
    <ul class="legend">{svg_burst()[1]}</ul>
    <p class="note">这是打字习惯的直接后果——想到哪儿发到哪儿，不憋着一句完整的。回复这类人时，他往往在你一句还没发完时就回了一条。</p>
  </div>
</section>

<section>
  <div class="no">05 — 速度</div>
  <div>
    <h2>二十一秒的手</h2>
    <p class="lede">从对方发来到我发出第一条：中位 <b>{lat_median} 秒</b>，{lat_60}% 在一分钟内，P90 {lat_p90} 秒（约 {lat_p90//60} 分）。</p>
    {svg_latency()}
    <p class="note">对数横轴，每个柱子一个区间。口径：对方那串消息的第一条 → 我这一轮的第一条。峰值在 <b>10–30 秒</b>（34.5%），3–30 秒内合计 {lat_fast:.0f}%：多数时候不是秒回，是"看到就回"。拖过一小时的只有 8%。</p>
  </div>
</section>

<section>
  <div class="no">06 — 作息</div>
  <div>
    <h2>一天里什么时候开口</h2>
    <p class="lede">横轴 0–23 点，纵轴周一到周日。颜色越深，那一小时发得越多。</p>
    {svg_heatmap()}
    <p class="note">颜色由浅到深 ＝ 每小时 0 → {fmt(hw_max)} 条；最深的一格是 {PEAK_TXT}。10–18 点是主场，17 点最高（7.8%）；3–6 点几乎为零。周末总量比工作日少三分之一，但凌晨 0–6 点的量反而翻倍——睡得晚、起得也晚：周末 6–9 点的量只有工作日的 <b>一半</b>。</p>
  </div>
</section>

<section>
  <div class="no">07 — 口头禅</div>
  <div>
    <h2>高频词长得像语气</h2>
    <p class="lede">字号按出现次数缩放。排在前面的词几乎都不是实词，是节奏本身。</p>
    <ul class="phrases">{phr}</ul>
    <p class="note">这些不是"词汇量"，是"起手式"。模仿一个人的语气，先抓住这几个词出现的位置，比背诵长句有效得多。</p>
  </div>
</section>

<section>
  <div class="no">08 — 称呼</div>
  <div>
    <h2>「宝」系称呼</h2>
    <p class="lede">同一个字衍生出一整套称呼，按亲密度与场合切换。数字是出现次数。</p>
    <table><tbody>{addr_rows}</tbody></table>
    <p class="note">称呼的选择随对象变化极大：对伴侣用「宝 / 宝宝 / 宝儿」，对工作对象退回「姐 / 哥 / 老师」。同一句话换错称呼，语气就全错了。</p>
  </div>
</section>

<section>
  <div class="no">09 — 场合</div>
  <div>
    <h2>私聊更短、更软</h2>
    <p class="lede">同一个人，在私聊和群聊里是两种写法。</p>
    <table class="cmp">
      <thead><tr><th></th><th class="num">私聊</th><th class="num">群聊</th><th></th></tr></thead>
      <tbody>
        <tr><th>消息数</th><td class="num">{fmt(pv['n'])}</td><td class="num">{fmt(gp['n'])}</td><td class="dim">99.6% 的文本在私聊</td></tr>
        <tr><th>平均字数</th><td class="num">{pv['len']}</td><td class="num">{gp['len']}</td><td class="dim">群里要多说两个字</td></tr>
        <tr><th>无标点</th><td class="num">{pv['punct']}%</td><td class="num">{gp['punct']}%</td><td class="dim">差别不大</td></tr>
        <tr><th>语气词</th><td class="num">{pv['tone']}%</td><td class="num">{gp['tone']}%</td><td class="dim">私聊几乎翻倍</td></tr>
        <tr><th>Emoji</th><td class="num">{pv['emoji']}%</td><td class="num">{gp['emoji']}%</td><td class="dim">都极少，用文字表情代替</td></tr>
      </tbody>
    </table>
    <p class="note">文字表情（<code>[捂脸]</code>×{fmt(dict(P['top_phrases']).get('捂脸', 0))}、<code>[破涕为笑]</code>）承担了 emoji 的活。</p>
  </div>
</section>

<section>
  <div class="no">10 — 原文</div>
  <div>
    <h2>切片</h2>
    <p class="lede">真实对话，未改写。看节奏，不看内容。</p>
    <div class="grid2">{slices}</div>
  </div>
</section>

<section>
  <div class="no">11 — 反模式</div>
  <div>
    <p class="pull">「像」不是靠长句和形容词堆出来的，是靠不写什么。</p>
    <ul class="dont">
      <li>不要补全标点。写「好的，我明天过去。」就已经不是这个人了。</li>
      <li>不要一次说完。他把一句话拆成三四条，逐条冒出来。</li>
      <li>不要用 emoji 表情绪。这里 emoji 出现率 {P['emoji_pct']}%，文字表情才是主力。</li>
      <li>不要礼貌用语成串。「不好意思打扰了」这类句子在这份语料里几乎不存在。</li>
      <li>不要拉长句子。平均 {P['len_mean']} 字，超过 {P['len_p90']} 字就已经越界。</li>
      <li>不要每次都回。{lat_median} 秒是常态，但忽略和已读不回同样属于模式。</li>
    </ul>
  </div>
</section>

<footer>
  <p>统计口径：导出库 <code>export/wechat.db</code> 中 <code>direction='out' AND type='文本'</code> 的 {fmt(N)} 条消息，按聊天窗口切分轮次（相邻 ≤120s 计同一轮）。所有数据本地生成，页面不含任何外部请求。</p>
  <p>同族文件：<code>persona/PROFILE.md</code> 画像卡 · <code>persona/system_prompt.md</code> 可粘贴提示词 · <code>persona/fewshot.md</code> 16 段示例 · <code>persona/persona.json</code> 原始统计。生成脚本 <code>persona/make_viz.py</code>。</p>
</footer>

</div>
</body>
</html>
"""

for i in range(len(SECTIONS)):
    HTML = HTML.replace("<section>", f'<section id="s{i+1:02d}">', 1)

out = os.path.join(HERE, "index.html")
open(out, "w", encoding="utf-8").write(HTML)
print("wrote", out, len(HTML), "bytes")
print("lat n=", len(lat), "median", lat_median, "p90", lat_p90)
print("len_hist", len_hist)
print("hw_max", hw_max)
