# 架构

## 一句话

**离线读、内存快照、只读查询、能力分层**：所有能力都建立在「拿到密钥 → 克隆库 → 只读 SQL」之上，上层只关心会话和消息，不关心 SQLCipher。

## 分层

```
┌──────────────────────────────────────────────────────────────┐
│  入口层    wxr CLI  ·  DSH 插件页面  ·  OpenClaw 工具  ·  HTTP │
├──────────────────────────────────────────────────────────────┤
│  能力层    digest 日报 · chatquery 检索 · watcher 监听         │
│            daily 统计 · autoreply 草稿/自动回复 · persona 画像  │
├──────────────────────────────────────────────────────────────┤
│  语义层    core：会话 / 消息 / 发送者 / 搜索 / 发送            │
├──────────────────────────────────────────────────────────────┤
│  基础层    wx：快照 · 只读查询 · zstd                          │
│            config：账号 / 密钥 / 路径（唯一来源）              │
├──────────────────────────────────────────────────────────────┤
│  工具层    wxq（只读查询）· wxdec（解密）· wxhook（抓钥）      │
└──────────────────────────────────────────────────────────────┘
```

依赖是**单向**的：上层可以依赖下层，反过来不行。`wx` 不认识 `core`，`core` 不认识 `digest`。

## 目录

| 路径 | 职责 |
|---|---|
| `src/wxr/config.py` | 账号、密钥、所有路径。**唯一**允许读配置文件的地方 |
| `src/wxr/wx.py` | APFS 克隆快照、`wxq` 只读查询、zstd 解压、联系人/会话名 |
| `src/wxr/zstd.py` | ctypes 调系统 `libzstd`，解 `WCDB_CT=4` 的正文 |
| `src/wxr/core.py` | 会话语义：`chat_list` / `messages` / `names` / `me` / 发送 |
| `src/wxr/llm.py` | 模型调用（OpenAI 兼容 / Anthropic），失败回落到本地规则 |
| `src/wxr/chatquery.py` | 「谁 + 时间 + 谁说的」检索 + 总结 |
| `src/wxr/digest.py` | 某天「我参与过」的日报 |
| `src/wxr/watcher.py` | 按 `local_id` 水位增量监听 |
| `src/wxr/daily.py` | 当日统计 + 未回私聊 |
| `src/wxr/notify.py` | 通知通道（macos / wecom / inbox / stdout / wechat） |
| `src/wxr/autoreply.py` | 自动回复引擎（默认关、dry-run） |
| `src/wxr/make_skill.py` | 从聊天记录生成回复风格 skill |
| `src/wxr/web/` | 本地 HTTP 服务 + 三栏页面 |
| `src/wxr/pipeline/` | 离线批处理：导出、建库、静态页、画像（`wxr pipeline <name>`） |
| `src/wxr/cli.py` | 统一入口，把子命令分发给上面这些 |
| `wxr` | 免安装启动器：`PYTHONPATH=src python3 -m wxr.cli` |
| `tools/` | C 工具源码（wxq / wxdec / wxsql / wxhook / 取证辅助） |
| `plugins/dsh/` | DSH 插件（左侧栏「微信记录」整页） |
| `integrations/openclaw/` | OpenClaw 工具（`wx_chat` / `wx_digest`） |
| `tests/` | 冒烟测试，不需要微信在跑 |

## 数据流

```
db_storage/*.db  (SQLCipher)
      │  cp -c 克隆（毫秒级，不动原文件）
      ▼
 /tmp 或 ~/.cache/wxr 下的副本
      │  wxq <db> <key> "select …"（READONLY + 只允许 SELECT）
      ▼
 TSV（BLOB 走 0x…，NUL 安全）
      │  zstd 解压 / XML 抽文本 / Name2Id 映射发送者
      ▼
 core 的 dict（会话、消息）
      │
      ├── CLI（wxr chats / messages / search）
      ├── 日报 / 监听 / 助手页面
      └── 汇总库 export/wechat.db（pipeline/build_export）
```

**读路径只有一条**：不存在「某个功能偷偷 `sqlite3.connect` 原始库」的情况。要加新功能，从 `core` 取数据。

## 契约

### config

```python
config.account()        # wxid，缺了抛 ConfigError 并提示 wxr init
config.key(acc=None)    # 64 位十六进制
config.dbdir(acc=None)  # ~/Library/Containers/.../db_storage
config.export_db()      # 汇总库路径
config.state_path(name) # ~/.cache/wxr/<name>，放游标、日志、配置副本
config.wxq_path()       # build/wxq，回落到 PATH
```

优先级：环境变量 > `~/.config/wxr/config.json` > 兼容旧文件 `account_key.json` > 默认值。
**密钥只在运行时出现**，不写日志、不进仓库、不落 `state/`。

### core

```python
chat_list() -> [{username, name, kind, unread, last_ts, summary}]
messages(username, limit=60, before_ts=None, after_ts=None)
                -> [{id, ts, type, from, mine, sender, text}]
names()  -> {username: 展示名}
me()     -> 自己的 wxid
send(username, text, dry=False)   # 需要 WxAgent + 辅助功能授权
```

### pipeline

放在 `src/wxr/pipeline/` 的脚本约定：模块顶层执行（`runpy.run_module(..., run_name="__main__")` 触发），路径一律从 `config` 取。
新增一个批处理 = 放一个文件 + 在 `cli.PIPELINES` 里登记，不需要改别处。

## 怎么加新功能

**加一个命令**

1. `src/wxr/` 下写模块，用 `core` / `wx` 取数据；
2. `cli.py` 里加 subparser 和一个 `cmd_xxx`；
3. `tests/test_smoke.py` 的 `test_cli_help` 里补一行断言。

**加一个数据维度**（比如「统计每个人的平均回复延迟」）

改 `core.py` 加函数，或新模块直接组合 `messages()`。不要绕过 `wx` 去连库——那样就拿不到快照和只读保护。

**加一个通知通道**

在 `notify.py` 里加 `_xxx()`，在 `send()` 的分发字典里登记，`channels` 配置加一个键。

**加一个前端**

- 轻量：`pipeline/gen_html.py` 出静态页；
- 交互：`web/server.py` 加接口 + `web/ui.html` 加面板；
- 宿主集成：`plugins/dsh/` 照样板加 slot 注册。

**换一个聊天软件**

`core` 是唯一需要替换的语义层：实现 `chat_list/messages/names/me` 四个函数，上层全部复用。

## 工程约束

- **只读**：`wxq` 打开库用 `SQLITE_OPEN_READONLY`，且 prepare 前拒绝非 SELECT（返回码 6）。测试里可以断言这一点。
- **不碰运行中的文件**：全部走 `cp -c` 克隆；克隆失败才回落普通拷贝。
- **无第三方依赖**：Python 只用标准库；zstd 走 ctypes；C 工具静态链接 sqlcipher。
- **密钥不出本机**：仓库、日志、`git` 里都不允许出现 64 位十六进制主密钥。
- **失败要能看懂**：配置缺失抛 `ConfigError` 并给下一步命令；模型不可用时回落到本地规则。

## 测试与发布

```bash
make tools     # 编译 C 工具到 build/
make test      # pytest：导入、配置、CLI、资源
make dist      # 打 DSH 插件 tgz
```

测试不依赖微信、密钥或真实数据；任何需要真实数据的验证都写在 `docs/USAGE.md` 的手动步骤里。
