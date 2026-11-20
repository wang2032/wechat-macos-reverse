"""wxr 命令行入口。

    wxr init --account <wxid> --key <64hex>   写配置并当场验证
    wxr status                                体检：配置 / 工具 / 数据 / 扩展
    wxr chats                                 会话列表
    wxr messages --chat <名字> [--limit N]    消息
    wxr search -q <关键词>                     全库搜索

    wxr ask ...       按「谁 + 时间 + 谁说的」查并总结（同 chatquery）
    wxr digest ...    某天「我参与过」的日报
    wxr watch ...     增量监听新消息
    wxr daily ...     当日统计
    wxr skill         用聊天记录生成回复风格 skill
    wxr web ...       本地助手服务 + 页面（:8777）

    wxr export        解密全部库 + 汇总成 export/wechat.db
    wxr html          生成可离线浏览的静态页
    wxr persona       语言画像（统计 + prompt）
    wxr serve         静态页 + 搜索服务（:8765）
    wxr pipeline <name> [args...]   直接跑任一 pipeline 模块
"""
from __future__ import annotations

import argparse
import os
import datetime as _dt
import pathlib
import runpy
import sys

from . import config as cfg

PIPELINES = {"export", "build_export", "gen_html", "gen_moments", "serve",
             "persona_build", "persona_gen", "viz"}

DELEGATES = {
    "ask": "wxr.chatquery",
    "digest": "wxr.digest",
    "watch": "wxr.watcher",
    "daily": "wxr.daily",
    "skill": "wxr.make_skill",
    "web": "wxr.web.server",
    "serve": "wxr.pipeline.serve",
}


def _delegate(module: str, argv: list[str]) -> None:
    """把参数原样交给某个模块的 __main__。"""
    old = sys.argv
    sys.argv = [module] + argv
    try:
        runpy.run_module(module, run_name="__main__")
    finally:
        sys.argv = old


def _mask(s: str) -> str:
    return f"{s[:4]}…{s[-4:]}" if len(s) > 12 else "***"


# ---------------------------------------------------------------- 命令

def cmd_init(a) -> int:
    c = cfg.load()
    if a.account:
        c["account"] = a.account
    if a.key:
        c["key"] = a.key.strip()
    p = cfg.save(c)
    print(f"写入 {p}（0600）")
    print(f"  account = {c.get('account')}")
    print(f"  key     = {_mask(c.get('key') or '')}")

    if a.verify:
        from . import wx
        db = cfg.dbdir() / "session/session.db"
        if not db.exists():
            print(f"  ⚠ 找不到 {db}")
            return 1
        n = wx.q(db, "select count(*) from sqlite_master", cfg.key())[0][0]
        print(f"  验证：session.db 读出 {n} 个对象 → 密钥可用")
    return 0


def cmd_status(a) -> int:
    c = cfg.load()
    print(f"配置文件   {cfg.config_path()} {'✓' if cfg.config_path().exists() else '✗'}")
    # 账号/密钥以 config 的解析结果为准（环境变量优先于文件）
    try:
        acct = cfg.account()
        src = "环境变量" if os.environ.get("WXR_ACCOUNT") else "配置"
        print(f"账号       {acct}（{src}）")
    except SystemExit:
        acct = ""
        print("账号       （未配置）  → ./wxr init --account <账号> --key <KEY>")
    try:
        print(f"密钥       {_mask(cfg.key(acct or None))}（环境变量或配置）")
    except SystemExit:
        print("密钥       （未配置）")
    print(f"wxq        {cfg.wxq_path()} {'✓' if cfg.wxq_path().exists() else '✗ 需 make tools'}")
    edb = cfg.export_db()
    print(f"汇总库     {edb} {'✓ %d MB' % (edb.stat().st_size // 1048576) if edb.exists() else '✗ 先跑 wxr export'}")
    print(f"状态目录   {cfg.state_dir()}")
    print(f"WxAgent    {'✓' if cfg.wxapp().exists() else '✗（只有微信内发送需要）'}")
    try:
        from . import llm
        st = llm.status()
        print(f"模型       {st.get('model')} @ {st.get('provider')} {'✓' if st.get('ok') else '（不可用）'}")
    except Exception as exc:  # 没配模型不影响其它功能
        print(f"模型       （不可用：{exc}）")
    return 0


def cmd_chats(a) -> int:
    from . import core
    rows = core.chat_list()
    for c in rows[:a.limit]:
        print(f"{c['name'][:32]:34} {c['kind']:6} {c['unread']:>3}  {c.get('summary') or ''}"[:140])
    print(f"\n共 {len(rows)} 个会话")
    return 0


def cmd_messages(a) -> int:
    from . import chatquery, core
    chat = chatquery.resolve(a.chat)
    if not chat:
        print(f"没找到会话：{a.chat}")
        return 1
    for m in core.messages(chat["username"], limit=a.limit):
        who = "我" if m["mine"] else (m["sender"] or m["from"])
        t = _dt.datetime.fromtimestamp(m["ts"]).strftime("%m-%d %H:%M")
        body = m["text"] or f"[{m.get('type') or '消息'}]"
        print(f"[{t}] {who}: {body}"[:200])
    return 0


def cmd_search(a) -> int:
    from .web.server import _search
    rows = _search(a.q, None, a.days, a.limit)
    for r in rows:
        t = _dt.datetime.fromtimestamp(r["ts"]).strftime("%m-%d %H:%M") if r.get("ts") else ""
        print(f"{r.get('name',''):22} [{t}] {r['text']}"[:180])
    print(f"\n{len(rows)} 条")
    return 0


def cmd_export(a) -> int:
    _delegate("wxr.pipeline.export", [])
    _delegate("wxr.pipeline.build_export", [])
    return 0


def cmd_html(a) -> int:
    _delegate("wxr.pipeline.gen_html", [])
    if not a.no_moments:
        _delegate("wxr.pipeline.gen_moments", [])
    print(f"打开：{cfg.export_dir()/'index.html'}")
    return 0


def cmd_persona(a) -> int:
    _delegate("wxr.pipeline.persona_build", [])
    _delegate("wxr.pipeline.persona_gen", [])
    if a.viz:
        _delegate("wxr.pipeline.viz", [])
        print(f"页面：{cfg.data_dir()/'persona/index.html'}")
    return 0


def cmd_pipeline(a) -> int:
    if a.name not in PIPELINES:
        print(f"未知 pipeline：{a.name}（可选：{', '.join(sorted(PIPELINES))}）")
        return 2
    _delegate(f"wxr.pipeline.{a.name}", a.rest)
    return 0


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wxr", description="WeChat macOS 本地数据工具包")
    sub = p.add_subparsers(dest="cmd")

    def add(name, fn, help_, **kw):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("init", cmd_init, "写配置并验证密钥")
    s.add_argument("--account")
    s.add_argument("--key")
    s.add_argument("--no-verify", dest="verify", action="store_false")

    add("status", cmd_status, "体检")

    s = add("chats", cmd_chats, "会话列表")
    s.add_argument("--limit", type=int, default=50)

    s = add("messages", cmd_messages, "看某个会话的消息")
    s.add_argument("--chat", required=True)
    s.add_argument("--limit", type=int, default=40)

    s = add("search", cmd_search, "全库搜索")
    s.add_argument("-q", "--query", dest="q", required=True)
    s.add_argument("--days", type=int, default=90)
    s.add_argument("--limit", type=int, default=50)

    s = add("export", cmd_export, "解密全部库并汇总")
    s = add("html", cmd_html, "生成静态聊天页")
    s.add_argument("--no-moments", action="store_true")

    s = add("persona", cmd_persona, "语言画像")
    s.add_argument("--viz", action="store_true", help="额外生成可视化页面")

    s = add("pipeline", cmd_pipeline, "直接跑 pipeline 模块")
    s.add_argument("name")
    s.add_argument("rest", nargs=argparse.REMAINDER)

    # 这些命令的参数原样转发给模块自己的 CLI（不走 argparse，避免吃掉 --who 之类）
    for name, help_ in [("ask", "按人+时间查记录并总结"),
                        ("digest", "某天我参与过的日报"),
                        ("watch", "增量监听新消息"),
                        ("daily", "当日统计"),
                        ("skill", "生成回复风格 skill"),
                        ("web", "本地助手服务 :8777"),
                        ("serve", "静态页搜索服务 :8765")]:
        sub.add_parser(name, help=help_, add_help=False)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in DELEGATES:
        _delegate(DELEGATES[argv[0]], argv[1:])
        return 0
    if not argv or argv[0] in ("-h", "--help"):
        build_parser().print_help()
        return 0
    a = build_parser().parse_args(argv)
    if not getattr(a, "fn", None):
        build_parser().print_help()
        return 0
    return a.fn(a) or 0


if __name__ == "__main__":
    raise SystemExit(main())
