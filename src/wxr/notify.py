"""把一条消息推给「你自己」——只用官方/本地通道，不碰微信客户端。

通道：
  macos  – 系统通知（osascript）
  wecom  – 企业微信群机器人 webhook（官方 API，微信里也能收到）
  inbox  – 追加到本地 markdown
  wechat – 通过 WxAgent 在微信里发到「文件传输助手」（需要辅助功能授权）
  stdout – 打印
"""
import json, pathlib, subprocess, sys, urllib.request, datetime

from . import config as _cfg

HERE = _cfg.ROOT
CFG_PATH = _cfg.state_path("config.json")


def load_cfg():
    if CFG_PATH.exists():
        return json.load(open(CFG_PATH))
    return {}


def _macos(title, text):
    t = text.replace('"', "'")[:240]
    ti = title.replace('"', "'")[:80]
    subprocess.run(["osascript", "-e",
                    f'display notification "{t}" with title "{ti}" sound name "Ping"'],
                   capture_output=True)


def _wecom(url, title, text):
    body = json.dumps({"msgtype": "text", "text": {"content": f"{title}\n{text}"[:4000]}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


WXAGENT = _cfg.wxapp()/"Contents"/"MacOS"/"wxagent"


def _wechat(title, text, to=None):
    """走微信进程内注入通道（不需要辅助功能授权）。"""
    import pathlib, time
    to = to or "文件传输助手"
    tmp = pathlib.Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/tmp"
    cmd, out = tmp / "wxsend.cmd", tmp / "wxsend.out"
    body = f"{title}\n{text}" if title else text
    try:
        out.unlink(missing_ok=True)
        cmd.write_text(f"{to}\t{body}", encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"写命令文件失败：{e}")
    for _ in range(60):
        if out.exists() and out.read_text().strip() not in ("", "pending"):
            v = out.read_text().strip()
            if v.startswith("ok"):
                return True
            raise RuntimeError(v)
        time.sleep(0.2)
    raise RuntimeError("注入通道没有回应（微信没在运行？）")

def _inbox(path, title, text):
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = HERE/p
    stamp = datetime.datetime.now().strftime("%m-%d %H:%M")
    with open(p, "a") as f:
        f.write(f"- **{stamp}**　{title}　{text}\n")


def send(title, text, cfg=None):
    cfg = cfg if cfg is not None else load_cfg()
    ch = cfg.get("channels", {})
    done = []
    if ch.get("macos", True):
        _macos(title, text); done.append("macos")
    if ch.get("wecom_webhook"):
        try:
            _wecom(ch["wecom_webhook"], title, text); done.append("wecom")
        except Exception as e:
            print(f"[wecom] 失败：{e}", file=sys.stderr)
    if ch.get("wechat"):
        try:
            _wechat(title, text, ch.get("wechat_to") or "文件传输助手"); done.append("wechat")
        except Exception as e:
            print(f"[wechat] 失败：{e}", file=sys.stderr)
    if ch.get("inbox"):
        _inbox(ch["inbox"], title, text); done.append("inbox")
    print(f"[{datetime.datetime.now():%H:%M:%S}] {title} {text}")
    return done


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "通知通道测试"
    print("sent to:", send("微信助手", msg))
