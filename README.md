# wechat-macos-reverse

**把本机微信 4.x 的聊天记录变成你能查询、能统计、能画页面的数据。**

纯本地、只读、离线：不联网、不发消息、不改微信数据。解密后的库和汇总库都在你自己机器上。

> 这是给自己账号做的数据工具，不是「微信客户端逆向破解」教程。只处理**你自己的**设备与账号。

---

## 它能做什么

| 能力 | 状态 | 入口 |
|---|---|---|
| 抓账号主密钥（每账号一次） | ✅ | `make tools` + `wxhook.dylib` |
| 解密 `db_storage/*.db` | ✅ | `wxr export` |
| 按「谁 + 时间 + 谁说的」查记录并总结 | ✅ | `wxr ask` |
| 全量汇总成单文件 SQLite | ✅ | `wxr export`（含 `build`） |
| 可离线浏览的聊天网页 / 朋友圈页 | ✅ | `wxr html` |
| 本地 HTTP 服务 + 三栏界面 | ✅ | `wxr web` |
| 某天「我参与过」的日报 | ✅ | `wxr digest` |
| 增量监听新消息 | ✅ | `wxr watch` |
| 语言画像（说话风格量化） | ✅ | `wxr persona` |
| 回复风格 skill（喂给模型） | ✅ | `wxr skill` |
| DSH 插件：左侧栏一页浏览 | ✅ | [`plugins/dsh`](plugins/dsh) |
| OpenClaw 工具 `wx_chat` / `wx_digest` | ✅ | [`integrations/openclaw`](integrations/openclaw) |
| 在微信里替人发消息 | ❌ | 见 §发送侧 |
| 解图片 / 语音 / 视频附件 | ❌ | 加密格式未破 |

功能细节与逐条用法：[`docs/FEATURES.md`](docs/FEATURES.md)、[`docs/USAGE.md`](docs/USAGE.md)。

---

## 安装

```bash
git clone https://github.com/wang2032/wechat-macos-reverse.git
cd wechat-macos-reverse

make tools                 # 编译 wxq / wxdec / wxsql / wxhook.dylib 到 build/
./wxr --help               # 免安装启动器（等价 PYTHONPATH=src python3 -m wxr.cli）

# 可选：装成全局命令
python3 -m pip install -e .
```

> 没装成功也不影响用：`./wxr` 是个 sh 包装，只依赖 Python 3 标准库。

编译需要 `brew install sqlcipher openssl@3`（只在编译期用；`wxq`/`wxdec` 静态链接，产物可单独拷走）。
运行时只需要 Python 3 标准库 + macOS 自带的 `libzstd`。

---

## 三步上手

### 1. 拿密钥

```bash
cp -cR /Applications/WeChat.app ./WeChatHook.app
# entitlements = 原版 + disable-library-validation + allow-dyld-environment-variables
codesign -f -s - --entitlements docs/entitlements.wx.plist ./WeChatHook.app/Contents/MacOS/WeChat

DYLD_INSERT_LIBRARIES=$PWD/build/wxhook.dylib ./WeChatHook.app/Contents/MacOS/WeChat
```

登录目标账号，日志里 `rounds=256000` 那条的 `pw` 就是主密钥：

```
PBKDF2 alg=2 pwlen=32 saltlen=16 prf=5 rounds=256000 pw=<64 位 hex> salt=<32 位 hex>
```

细节与失败情形见 [`docs/USAGE.md`](docs/USAGE.md) 第一节（含 `-arch arm64e`、SIP、ad-hoc 重签的坑）。

### 2. 写配置

```bash
wxr init --account wxid_example_0001 --key <64 位 hex>   # 写 ~/.config/wxr/config.json (0600)
wxr status                                               # 体检：账号/密钥/工具/汇总库
```

密钥也可以只放环境变量 `WXR_DB_KEY`，不落盘。

### 3. 用

```bash
wxr chats                                   # 会话列表（按最后消息时间）
wxr messages --chat 老婆 --limit 30         # 最近 30 条
wxr ask --who 羽毛球 --yesterday --ask "最后定了几点"
wxr search -q 分镜 --limit 20               # 全局搜索
wxr digest --date 2026-11-19                # 当天我参与过的会话日报
wxr export                                  # 全量导出 + 汇总库 export/wechat.db
wxr html                                    # 静态页面 export/index.html
wxr persona --viz                           # 语言画像 + 可视化页
wxr web                                     # 本地界面 http://127.0.0.1:8777
```

---

## 工作原理

```
db_storage/*.db (SQLCipher)
   │  cp -c 克隆（毫秒级，不动原文件）
   ▼
 /tmp 下的副本
   │  wxq <db> <key> "select …"（READONLY + 只允许 SELECT）
   ▼
 TSV → zstd 解压 → XML 抽文本 → Name2Id 映射发送者
   │
   ├─ wxr ask / digest / watch     查询与日报
   ├─ export/wechat.db             汇总库（四张表）
   └─ web / DSH 插件 / 静态页面     界面
```

微信在运行时用 `sqlite3_key(db, key, 32)` 把 **32 字节账号级主密钥**交给 SQLCipher：同账号所有库共用一把 key，每个库各有自己的 16 字节 salt；key 不落盘，也不以 `x'<key><salt>'` 字符串形式存在（4.0.x 才是那样）。
所以正确做法是从 `CCKeyDerivationPBKDF` 的入参里截获它。原理与参数在 [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md)。

---

## 项目结构

```
src/wxr/            Python 包（config / wx / core / llm / 各能力模块 / web / pipeline）
tools/              C 工具：wxq（只读查询）、wxdec（解密）、wxhook（抓钥）、取证辅助
plugins/dsh/        DeepSeek Harness 插件：侧栏「微信记录」整页 + 本地 8778 服务
integrations/openclaw/  OpenClaw 工具：wx_chat、wx_digest
tests/              冒烟测试（不需要微信、不需要密钥）
docs/               ARCHITECTURE / FEATURES / USAGE / BUILD / REVERSE_ENGINEERING / RECOVERY
```

分层与扩展方式见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：
**基础层（wx）→ 语义层（core）→ 能力层 → 入口层（CLI / 页面 / 插件）**，依赖单向。
加一个新命令 = 写一个模块 + 在 `cli.py` 注册 + 一条测试。

---

## 发送侧：为什么是 ❌

个人微信没有官方发送接口。三条路都试过并记录在 [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md)：

1. **辅助功能（AX）+ 模拟按键** —— 需要用户授「辅助功能」权限，还得让微信在前台抢焦点。
2. **注入 dylib 往自己的事件队列投递 NSEvent / CGEvent** —— 微信 4.2 的会话界面是 Qt（`QNSWindow`/`QNSView`）自绘的，五种投递方式全部返回成功但消息没进库。
3. **协议层命令**（`sendmsg`=2 / `newsendmsg`=237 / `sendappmsg`=107）—— 需要 protobuf 结构与登录态，且违反使用协议。

所以本仓库**只读**。要自动发通知，用系统通知、企业微信群机器人这类正规通道。

---

## 常见坑

**`file is not a database (26)`** —— key 或用法不对。必须是 `sqlite3_key(db, <32 字节二进制>, 32)`，`PRAGMA key="x'…'"` 和 `PRAGMA key='<hex 文本>'` 都是错的（CLI 表达不了二进制口令）。

**每个账号一把 key** —— 小号 key 解不开大号库。

**`unsupported file format` / 打不开** —— 先 `cp -c` 克隆再查，别对正在写的库直接跑。

**`.factory` 目录** —— 微信偶尔会把库挪到 `message_0.db.factory/<时间戳>/` 并用新 salt 重新加密，那份档案用原 key 打不开。出事第一件事：**停掉微信，把 `.factory` 和你的克隆都拷出来**。复盘见 [`docs/RECOVERY.md`](docs/RECOVERY.md)。

**卡片消息变 `[卡片消息]`** —— 应用消息正文是 XML，抽取失败时会退化为标签；`wxr export` 里用正则而不是 `ElementTree`（macOS 自带的 Python 可能缺 `expat`）。

---

## 安全与边界

- 仓库里**没有**任何真实密钥、wxid、聊天内容；示例统一 `wxid_example_0001` / `<KEY>`。
- 主密钥等价于你账号聊天数据的钥匙：别提交、别外发、别放进截图。
- 只用在自己账号、自己设备上；解密他人的库在多数司法辖区是违法的。
- 微信更新可能改变加密参数或库结构——升级后先跑 `wxr status` 和一条 `wxr chats` 验证。

---

## 参考

- [`ydotdog/wechat-export-macos`](https://github.com/ydotdog/wechat-export-macos)：4.0.x 的 `x'<key><salt>'` 扫描与 SQLCipher 参数，本项目的起点（4.2 上已失效）。
- SQLCipher 4 的页格式与 HMAC 计算。
- 微信 4.2 的 UI 栈是 Qt 而非 AppKit —— 这决定了发送侧所有 UI 注入路线都走不通。

MIT License，见 [`LICENSE`](LICENSE)。
