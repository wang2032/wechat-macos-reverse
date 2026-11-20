"""微信智能助手的数据层：读本地库（快照+解密）、发消息（WxAgent）。

读：APFS clone 一份 db_storage 快照，用 wxq 解密查询，不碰运行中文件。
写：进程外调 WxAgent.app 模拟按键（需要辅助功能授权）。
"""
import hashlib, json, os, pathlib, re, subprocess, sys, tempfile, time
import html as _html

from . import config as _cfg
from . import wx

HERE = _cfg.ROOT
ROOT = _cfg.ROOT
ACCOUNT = os.environ.get("WX_ACCOUNT") or ""


def account() -> str:
    """惰性解析：环境变量 → 配置 → 报错。"""
    return ACCOUNT or _cfg.account()
WXAPP = _cfg.wxapp()
WXAGENT = WXAPP / "Contents" / "MacOS" / "wxagent"
CFG_PATH = _cfg.state_path("config.json")

_cache = {"dir": None, "ts": 0.0, "tables": None, "id2user": None}
_lock_ts = 0.0

TYPE_TAG = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 48: "位置", 49: "卡片", 50: "通话", 10000: "系统"}


def cfg():
    if CFG_PATH.exists():
        return json.load(open(CFG_PATH))
    return {}


def save_cfg(c):
    CFG_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=1))


def _snap():
    now = time.time()
    if _cache["dir"] and now - _cache["ts"] < 1.0:
        return _cache["dir"]
    msgdb = wx.dbdir(account()) / "message/message_0.db"
    d = wx.snapshot([msgdb, pathlib.Path(str(msgdb) + "-wal"), pathlib.Path(str(msgdb) + "-shm")],
                    dest=f"/tmp/wxassist_{os.getpid()}")
    _cache.update(dir=d, ts=now)
    return d


def _msgdb():
    return _snap() / "message_0.db"


def _key():
    return wx.my_key(account())


def table_of(username):
    """Msg_<md5(username)>，不存在返回 None。"""
    t = "Msg_" + hashlib.md5(username.encode()).hexdigest()
    if _cache["tables"] is None:
        rows = wx.q(_msgdb(), "select name from sqlite_master where type='table' and name like 'Msg_%'", _key())
        _cache["tables"] = {r[0] for r in rows}
    return t if t in _cache["tables"] else None


def _id2user():
    if _cache["id2user"] is None:
        m = {}
        for rowid, uname in wx.q(_msgdb(), "select rowid,user_name from Name2Id", _key()):
            if uname:
                m[int(rowid)] = uname
        _cache["id2user"] = m
    return _cache["id2user"]


_names = {"ts": 0.0, "v": {}}


def names():
    if time.time() - _names["ts"] > 120 or not _names["v"]:
        db = wx.dbdir(account()) / "contact/contact.db"
        snap = wx.snapshot([db])
        out = {}
        for u, remark, nick, alias in wx.q(snap / "contact.db",
                                           "select username, remark, nick_name, alias from contact", wx.my_key(account())):
            out[u] = (remark or nick or alias or u)
        _names.update(ts=time.time(), v=out)
    return _names["v"]


def me():
    return account().rsplit("_", 1)[0]


def label(lt):
    base = int(lt or 0) & 0xFFFFFFFF
    return TYPE_TAG.get(base, f"type{base}")


def clean(body):
    if not body:
        return ""
    if body.lstrip().startswith("<"):
        for tag in ("title", "des"):
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", body, re.S)
            if m:
                return _html.unescape(m.group(1).strip())[:120]
        return ""
    return body.strip()


def chat_list():
    db = wx.dbdir(account()) / "session/session.db"
    snap = wx.snapshot([db, pathlib.Path(str(db) + "-wal"), pathlib.Path(str(db) + "-shm")])
    rows = wx.q(snap / "session.db",
                "select username,last_timestamp,unread_count,summary from SessionTable", wx.my_key(account()))
    nm = names()
    out = []
    for u, ts, un, summary in rows:
        if not u or u.startswith("gh_") or u == "brandsessionholder":
            continue
        t = table_of(u)
        if not t:
            continue
        out.append({
            "username": u,
            "name": nm.get(u) or summary or u,
            "kind": "group" if u.endswith("@chatroom") else ("filehelper" if u == "filehelper" else "person"),
            "last_ts": int(ts or 0),
            "unread": int(un or 0),
            "summary": summary or "",
            "table": t,
        })
    out.sort(key=lambda c: -c["last_ts"])
    return out


def messages(username, limit=60, before_ts=None, after_ts=None):
    t = table_of(username)
    if not t:
        return []
    key = _key()
    where = []
    if before_ts:
        where.append(f"create_time < {int(before_ts)}")
    if after_ts:
        where.append(f"create_time > {int(after_ts)}")
    w = ("where " + " and ".join(where)) if where else ""
    rows = wx.q(_msgdb(),
                f"select local_id,local_type,create_time,real_sender_id,message_content,"
                f"WCDB_CT_message_content from {t} {w} order by local_id desc limit {int(limit)}", key)
    i2u = _id2user()
    nm = names()
    my = me()
    out = []
    for lid, lt, ts, sid, content, ctype in reversed(rows):
        body = wx.text_of(content, ctype) if content not in (None, "") else ""
        snd, body = wx.split_sender(body)
        snd = snd or i2u.get(int(sid or 0), "")
        mine = (snd == my)
        out.append({
            "id": int(lid), "ts": int(ts or 0), "type": label(lt),
            "from": "me" if mine else (nm.get(snd) or snd or "对方"),
            "sender": snd, "mine": mine,
            "text": clean(body),
            "raw_len": len(body or ""),
        })
    return out


def latest_ts(username):
    rows = messages(username, limit=1)
    return rows[-1]["ts"] if rows else 0



CONTAINER_TMP = pathlib.Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/tmp"


def _inline_send(target, text, timeout=14):
    """走注入的 wxsend.dylib：写命令文件 + 等结果文件。不需要任何系统授权。"""
    cmd = CONTAINER_TMP / "wxsend.cmd"
    out = CONTAINER_TMP / "wxsend.out"
    try:
        if out.exists():
            out.unlink()
        cmd.write_text(f"{target}\t{text}", encoding="utf-8")
    except Exception as e:
        return f"err:{e}"
    end = time.time() + timeout
    while time.time() < end:
        try:
            if out.exists() and out.stat().st_size:
                v = out.read_text(encoding="utf-8").strip()
                if v == "pending":
                    time.sleep(0.2)
                    continue
                return v
        except Exception:
            pass
        time.sleep(0.15)
    return "err:timeout"


def _inline_ping():
    cmd = CONTAINER_TMP / "wxsend.cmd"
    out = CONTAINER_TMP / "wxsend.out"
    try:
        if out.exists():
            out.unlink()
        cmd.write_text("PING", encoding="utf-8")
    except Exception:
        return ""
    end = time.time() + 3
    while time.time() < end:
        if out.exists() and out.stat().st_size:
            return out.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    return ""

def _wx_run(args, timeout=60, mode="send"):
    """跑 wxagent：先用二进制直跑（父进程被授权时最快）；不行再用 LaunchServices 起 app。

    通过 open 启动时 TCC 认得是 WxAgent.app 自己，所以用户在「辅助功能」里给这个 app
    授权就能用，不必给 Terminal/Python/node 授权。
    """
    out_file = pathlib.Path(tempfile.gettempdir()) / f"wxagent_{os.getpid()}_{int(time.time()*1000)}.json"
    attempts = [(0, [str(WXAGENT)] + args + ["--out", str(out_file)]),
                (1, ["open", "-n", "-a", str(WXAPP), "--args"] + args + ["--out", str(out_file)])]
    last = {"code": -1, "msg": "wxagent 没有输出"}
    for kind, cmd in attempts:
        try:
            if out_file.exists():
                out_file.unlink()
            if kind == 0:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                text = (p.stdout or "") + (p.stderr or "")
            else:
                subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                text = ""
            deadline = time.time() + timeout
            while time.time() < deadline:
                if out_file.exists() and out_file.stat().st_size:
                    break
                time.sleep(0.2)
            if out_file.exists():
                d = json.loads(out_file.read_text())
                last = {"code": int(d.get("code", -1)), "msg": d.get("msg", "")}
            elif text.strip():
                last = {"code": p.returncode, "msg": text.strip()}
        except Exception as e:
            last = {"code": -1, "msg": str(e)}
        if mode == "check":
            if "ax_trusted=1" in last["msg"]:
                break
        else:
            if last["code"] != 3:      # 3 = 未授权，换下一条路再试
                break
    try:
        if out_file.exists():
            out_file.unlink()
    except Exception:
        pass
    return last


def ax_status():
    """只有注入通道。绝不拉起 WxAgent —— 那会让 macOS 把授权请求算到 python/node 头上，
    页面轮询 /api/status 时就会反复弹窗。"""
    ping = _inline_ping()
    if ping.startswith("pong"):
        m = dict(re.findall(r"(\w+)=(\d+)", ping))
        return {"trusted": True, "inline": True, "wechat_pid": 0,
                "windows": int(m.get("windows", 0)), "msg": ping}
    return {"trusted": False, "inline": False, "wechat_pid": 0, "windows": 0,
            "msg": ping or "注入通道没有响应"}


def send(username, text, dry=False):
    """发消息：只走进程内注入（不需要任何系统授权）。"""
    nm = names()
    target = nm.get(username) or username
    if dry:
        return {"ok": True, "target": target, "code": 0, "out": "[dry]", "err": "", "via": "dry"}
    inline = _inline_send(target, text)
    ok = inline.startswith("ok")
    return {"ok": ok, "target": target, "code": 0 if ok else 5,
            "out": inline if ok else "", "err": "" if ok else inline, "via": "inline"}
