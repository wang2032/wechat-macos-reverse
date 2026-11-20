"""统一配置层：账号、密钥、路径只在这里解析。

优先级（前者覆盖后者）：
    1. 环境变量   WXR_ACCOUNT / WXR_DB_KEY / WXR_CONFIG / WXR_STATE / WXR_WXQ / WXR_EXPORT_DB
    2. 配置文件   ~/.config/wxr/config.json（可用 WXR_CONFIG 改）
    3. 仓库默认   见下面的常量
    4. 兼容旧文件 account_key.json（只有 account/key 两项）

配置文件形状：

    {
      "account": "wxid_xxxxxxxx",
      "key": "<64 位十六进制>",
      "wxq": "build/wxq",
      "export_db": "export/wechat.db",
      "channels": {"macos": true, "stdout": true, "inbox": false, "wecom": false},
      "wecom_webhook": "",
      "llm": {"api": "openai", "base_url": "https://api.deepseek.com",
              "model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY"}
    }

密钥只从配置/环境读，永远不写进仓库。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]

WECHAT_FILES = pathlib.Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"

DEFAULT_EXPORT_DB = ROOT / "export" / "wechat.db"

_CACHE: dict = {"cfg": None, "path": None}


class ConfigError(SystemExit):
    """配置缺失时给出可执行的提示，而不是抛栈。"""


# ---------------------------------------------------------------- 位置

def config_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("WXR_CONFIG") or pathlib.Path.home() / ".config/wxr/config.json")


def state_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("WXR_STATE") or pathlib.Path.home() / ".cache/wxr")
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(name: str) -> pathlib.Path:
    return state_dir() / name


def data_dir() -> pathlib.Path:
    """生成物（persona/skill/digest）默认落这里。"""
    d = ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_dir() -> pathlib.Path:
    d = ROOT / "export"
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_db() -> pathlib.Path:
    env = os.environ.get("WXR_EXPORT_DB")
    if env:
        return pathlib.Path(env).expanduser()
    p = get("export_db")
    return pathlib.Path(p).expanduser() if p else DEFAULT_EXPORT_DB


def work_dir() -> pathlib.Path:
    d = ROOT / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir() -> pathlib.Path:
    d = ROOT / "out"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool(name: str) -> pathlib.Path:
    """仓库内编译产物（build/<name>），找不到回落到 PATH。"""
    p = ROOT / "build" / name
    if p.exists():
        return p
    w = shutil.which(name)
    if w:
        return pathlib.Path(w)
    return p


def wxq_path() -> pathlib.Path:
    env = os.environ.get("WXR_WXQ")
    if env:
        return pathlib.Path(env).expanduser()
    p = get("wxq")
    if p:
        q = pathlib.Path(p).expanduser()
        return q if q.is_absolute() else ROOT / q
    return tool("wxq")


def wxapp() -> pathlib.Path:
    return pathlib.Path(get("wxapp") or (ROOT / "WxAgent.app"))


def skill_path() -> pathlib.Path:
    p = get("skill")
    if p:
        return pathlib.Path(p).expanduser()
    return data_dir() / "skill.md"


# ---------------------------------------------------------------- 读写

def load() -> dict:
    path = config_path()
    if _CACHE["cfg"] is not None and _CACHE["path"] == path:
        return _CACHE["cfg"]

    cfg: dict = {}
    legacy = ROOT / "account_key.json"
    if legacy.exists():
        try:
            cfg.update({k: v for k, v in json.loads(legacy.read_text()).items()
                        if k in ("account", "key")})
        except Exception:
            pass
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text()))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"配置文件不是合法 JSON：{path}\n  {exc}")

    _CACHE["cfg"], _CACHE["path"] = cfg, path
    return cfg


def save(cfg: dict) -> pathlib.Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    path.chmod(0o600)
    _CACHE["cfg"], _CACHE["path"] = cfg, path
    return path


def get(key: str, default=None):
    return load().get(key, default)


# ---------------------------------------------------------------- 账号 / 密钥

def account() -> str:
    env = os.environ.get("WXR_ACCOUNT")
    if env:
        return env
    acc = get("account")
    if not acc:
        raise ConfigError(
            "还没配账号。先跑：\n"
            "  wxr init --account <你的 wxid> --key <64 位十六进制>\n"
            "或设置环境变量 WXR_ACCOUNT / WXR_DB_KEY"
        )
    return acc


def key(acc: str | None = None) -> str:
    env = os.environ.get("WXR_DB_KEY")
    if env:
        return env.strip()
    cfg = load()
    k = cfg.get("key")
    if not k:
        raise ConfigError(
            "还没配密钥。抓钥见 docs/USAGE.md「第一步」，然后：\n"
            "  wxr init --account <wxid> --key <64 位十六进制>"
        )
    if acc and cfg.get("account") and acc != cfg["account"]:
        raise ConfigError(f"配置里是 {cfg['account']}，不是 {acc}；换账号请改 WXR_ACCOUNT")
    return k.strip()


def account_dir(acc: str | None = None) -> pathlib.Path:
    return WECHAT_FILES / (acc or account())


def dbdir(acc: str | None = None) -> pathlib.Path:
    return account_dir(acc) / "db_storage"


def channels() -> dict:
    return load().get("channels") or {"macos": True, "stdout": True}


def wecom_webhook() -> str:
    return os.environ.get("WXR_WECOM_WEBHOOK") or get("wecom_webhook") or ""
