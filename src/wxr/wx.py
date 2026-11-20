"""读取加密中的微信库（快照副本，不碰运行中的文件句柄）。"""
import json, os, pathlib, shutil, subprocess, sys

from . import config as _cfg
from .zstd import decompress as _decompress

ROOT = _cfg.ROOT
WXQ = _cfg.wxq_path()
BASE = _cfg.WECHAT_FILES
DEFAULT_ACCOUNT = ""          # 留给调用方显式传入；CLI 会从 config 解析


def _acc(account=None):
    return account or _cfg.account()


def account_dir(account=None):
    return BASE/_acc(account)


def dbdir(account=None):
    return account_dir(account)/"db_storage"


def my_key(account=None):
    return _cfg.key(account)


def snapshot(paths, dest=None):
    """APFS clone（毫秒级、CoW），拿不到就普通拷贝。返回快照目录。"""
    dest = pathlib.Path(dest or (pathlib.Path("/tmp")/f"wxsnap_{os.getpid()}"))
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        p = pathlib.Path(p)
        if not p.exists():
            continue
        tgt = dest/p.name
        if tgt.exists():
            tgt.unlink()
        try:
            subprocess.run(["cp", "-c", str(p), str(tgt)], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            shutil.copy2(p, tgt)
    return dest


def unesc(s):
    if s == r"\N":
        return None
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i+1 < len(s):
            n = s[i+1]
            out.append({"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def q(db, sql, key):
    r = subprocess.run([str(WXQ), str(db), key, sql], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"wxq rc={r.returncode}: {r.stderr.strip()[:300]}")
    rows = []
    for line in r.stdout.splitlines():
        cells = [unesc(x) for x in line.split("\t")]
        cells = [bytes.fromhex(c[2:]) if c and c.startswith("0x") else c for c in cells]
        rows.append(cells)
    return rows


def text_of(content, ctype):
    """message_content 可能是 zstd 压缩的 bytes 或 str。"""
    if content is None:
        return ""
    b = content if isinstance(content, bytes) else content.encode("utf8", "surrogatepass")
    if ctype and ctype != "0":
        b = _decompress(b)
    return b.decode("utf8", "replace")


def split_sender(text):
    if text.startswith("<") or ":\n" not in text[:80]:
        return "", text
    head, body = text.split(":\n", 1)
    return head, body


def names(account=None):
    """username -> 展示名"""
    db = dbdir(account)/"contact/contact.db"
    snap = snapshot([db])
    rows = q(snap/"contact.db", "select username, remark, nick_name, alias from contact", my_key(account))
    out = {}
    for u, remark, nick, alias in rows:
        out[u] = (remark or nick or alias or u)
    return out


def me(account=None):
    return _acc(account).rsplit("_", 1)[0]


def chats(account=None):
    db = dbdir(account)/"session/session.db"
    snap = snapshot([db, str(db)+"-wal", str(db)+"-shm"])
    rows = q(snap/"session.db",
             "select username, last_timestamp, unread_count, summary from SessionTable", my_key(account))
    return {u: dict(last=int(ts or 0), unread=int(un or 0), summary=s or "") for u, ts, un, s in rows}
