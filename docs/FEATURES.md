# 功能详解

这份文档按「能力层」把仓库和作者本机的工作流全部列出来：每项写清楚它**做什么、怎么调、读到什么、吐出什么、依赖什么、哪里会崩**。

图例：✅ 本仓库可直接用　🟡 本仓库有代码但需要你本机补配置　⬜ 作者本机的扩展模块（未开源，结构写在这里方便你照做）　❌ 没做通

---

## 0. 总览

| # | 能力 | 入口 | 状态 |
|---|---|---|---|
| 1 | 从运行中的微信抓每账号的 32 字节主密钥 | `tools/wxhook_dylib.c` | ✅ |
| 2 | 只读查询加密库（不解出整库） | `bin/wxq` | ✅ |
| 3 | 整库解密成明文 SQLite | `bin/wxdec` | ✅ |
| 4 | 内存取证辅助（扫符号 / 验密钥 / 找 salt） | `tools/{scan_keys,keytest,memgrep,probe,dumpregion}.c` | ✅ |
| 5 | 全量导出成可查询的汇总库 | `scripts/export.py` → `scripts/build_export.py` | ✅ |
| 6 | 生成可离线浏览的聊天网页 | `scripts/gen_html.py` / `gen_moments.py` | ✅ |
| 7 | 本地搜索服务（HTTP） | `scripts/serve.py` → `:8765` | ✅ |
| 8 | 按「谁 + 时间 + 谁说的」查记录并 AI 总结 | `scripts/chatquery.py` | ✅ |
| 9 | 每天「我参与过的」会话日报 | `wxdigest.py`（本地扩展） | ⬜ |
| 10 | 增量监听新消息 + 本地通知 | `selfnotify/watch_new.py` | ⬜ |
| 11 | 语言画像（把一个人说话方式量化 + 生成 prompt） | `scripts/persona_build.py` / `persona_gen.py` | ✅ |
| 12 | 用聊天记录生成「回复风格 skill」 | `assistant/make_skill.py` | ⬜ |
| 13 | 本地 Web 助手（浏览 / 总结 / 草稿 / 自动回复） | `assistant/server.py` → `:8777` | ⬜ |
| 14 | DSH 插件页面（左侧栏「微信记录」） | `dsh-plugin/` → `:8778` | ✅ |
| 15 | OpenClaw 工具 `wx_chat` / `wx_digest` | `plugin-wxchat/` / `plugin-wxdigest/` | ⬜ |
| 16 | 在微信里发消息 | — | ❌ |
| 17 | 解图片 / 语音 / 视频附件 | — | ❌ |

---

## 1. 基础层

### 1.1 抓主密钥（`tools/wxhook_dylib.c`）

**做什么**：在微信进程里拦截 `CCKeyDerivationPBKDF`，拿到每个库的 32 字节库密钥。

**原理**：微信用 SQLCipher，打开库时调 CommonCrypto 的 PBKDF2 派生 HMAC 密钥。用 `__DATA,__interpose` 把 `CCKeyDerivationPBKDF` 换成自己的函数，原函数从 `interposers[0].replacee` 取（链接期地址，dyld 不会重绑），调用前后把 `password`（就是库密钥）写日志。

**前提**（缺一不可）：
1. SIP 关闭（`csrutil status` → `disabled`）
2. 微信副本重签，entitlements 加 `com.apple.security.cs.disable-library-validation` + `com.apple.security.cs.allow-dyld-environment-variables`
3. `DYLD_INSERT_LIBRARIES` 启动
4. 编译加 `-arch arm64e`（微信主程序是 arm64e，arm64 会被 dyld 拒）

**关键代码点**：

```c
static const struct { const void *replacement; const void *replacee; }
interposers[] __attribute__((section("__DATA,__interpose"))) __attribute__((used)) = {
    { (const void *)my_pbkdf, (const void *)CCKeyDerivationPBKDF }
};
```

**输出**：日志里每个库一行 `PBKDF2 alg=2 pwlen=32 saltlen=16 prf=5 rounds=256000 pw=<64hex> salt=<32hex> caller=<addr>`。
`rounds=256000` 那些是真库密钥；`rounds=2` 是微信用来派生别的东西的二级派生，忽略。

**坑**：
- 沙盒写不了 `/tmp`，日志要写 `NSTemporaryDirectory()`
- helper 进程（`WeChatAppEx` 等）也会加载 dylib，必须用 `[[[NSBundle mainBundle] executablePath] hasSuffix:@"/Contents/MacOS/WeChat"]` 判定主进程
- 主线程不 drain main dispatch queue，只能用 `CFRunLoopPerformBlock`

### 1.2 只读查询（`bin/wxq`）

**做什么**：不复制、不解密整库，直接对加密库跑一条 SELECT，输出 TSV。

```bash
./bin/wxq <db 路径> <keyhex> "select count(*) from SessionTable"
```

- `sqlite3_open_v2(..., SQLITE_OPEN_READONLY, ...)`，prepare 前拒绝非 SELECT（`strncasecmp(q,"select",6)`），返回码 6
- BLOB 列自动转 `0x<hex>`（否则 `sqlite3_column_text` 遇 NUL 会截断）
- 输出按 `sqlite3_column_bytes` 转义 `\t \n \r \\`

**已验证的只读性**：同一 `session.db` 连查 5 次，`mtime` 与 sha256 都不变；`delete from SessionTable` 被拒（rc=6）。

**坑**：对**已解密的明文库**再传 key 会报 `prepare rc=26 file is not a database`——明文不需要 key。

### 1.3 整库解密（`bin/wxdec`）

```bash
./bin/wxdec in.db <keyhex> out.db
```

内部：`sqlite3_key(db, key, 32)` → `ATTACH DATABASE '<out>' AS p KEY ''` → `SELECT sqlcipher_export('p')`。

**坑**：
- `sqlite3_backup_*` 对加密库不可用（`backup is not supported with encrypted databases`）
- `sqlcipher` CLI 的 `PRAGMA key="x'…'"`（raw key 语义）和 `PRAGMA key='<hex>'`（文本口令语义）**都不行**，微信是二进制口令，必须自己调 `sqlite3_key`
- 失败码：3=open、4=key、5=attach、6=export

### 1.4 内存取证辅助

| 工具 | 用途 |
|---|---|
| `scan_keys` | 扫内存找 `x'<key+salt>'` 字符串（4.0.x 有效，4.2 已失效，0 命中） |
| `keytest` | 给一段内存 + 一个加密库，按滑动窗口试 32 字节 key，用 page-1 HMAC 判定。1MB ≈ 4s |
| `memgrep` | 通用内存搜索，支持 `hex:` 二进制 needle |
| `probe` | 只找 `x'<hex>` 模式 |
| `dumpregion` | 把目标某地址区间的内存原样 dump 到文件 |
| `ptry` | `ptrace(PT_ATTACH)` 可用性验证（本机在 SIP 关闭 + debugger entitlement 下可行） |

---

## 2. 数据层

### 2.1 全量导出（`scripts/export.py`）

```bash
python3 scripts/export.py --account wxid_example_0001 --key <KEY>
```

流程：`db_storage/**/*.db` + `-wal` + `-shm` 复制到 `work/<账号>/` → 逐库 `wxdec` → `out/<账号>/` → 用 `select count(*) from sqlite_master` 校验。

**实测**：20 个库 0 失败，最大 `message/message_0.db` 287MB。

### 2.2 汇总库（`scripts/build_export.py`）

把散落的 180 张 `Msg_<md5>` 表、联系人、朋友圈汇成一个 `export/wechat.db`：

| 表 | 字段 |
|---|---|
| `messages` | `id, chat, local_id, ts, sender, sender_name, direction, raw_type, type, text` |
| `chats` | `username, name, kind, msg_count, first_ts, last_ts, summary` |
| `contacts` | `username, display, nick, remark, alias, kind` |
| `moments` | `ts, user, name, text, images, loc` |

**实测**：421,324 条消息 / 180 会话 / 8,002 联系人 / 2,338 朋友圈。

**坑**：`WCDB_CT_message_content=4` 时正文是 zstd 压缩（magic `28 B5 2F FD`），要用 `zstdlib.py`（ctypes 调 `libzstd`）；Python 3.14 缺 `expat` 时 `ElementTree` 会静默失败，卡片消息全变 `[卡片消息]`——用正则解析 XML 更稳。

### 2.3 静态页面（`scripts/gen_html.py` / `gen_moments.py`）

- `gen_html.py` → `export/index.html`（会话列表）+ `export/chats/*.html`（每会话一页，气泡样式，锚点 `#m<local_id>`）+ `export/chats.json`
- `gen_moments.py` → `export/moments.html`

纯静态，双击就能看，不需要服务。

### 2.4 搜索服务（`scripts/serve.py`）

```bash
python3 scripts/serve.py        # http://127.0.0.1:8765
```

`/api/search?q=&limit=` → 走 `messages.text LIKE`，返回会话文件名 + 消息锚点，点进去直接定位。

---

## 3. 查询层

### 3.1 按人 + 时间查（`scripts/chatquery.py`）

```bash
python3 scripts/chatquery.py --who "老婆" --days 3
python3 scripts/chatquery.py --who 羽毛球 --from 2026-11-01 --to 2026-11-18
python3 scripts/chatquery.py --who 老张 --yesterday --ask "他到底想约哪天"
python3 scripts/chatquery.py --who 项目群 --by 老王            # 只看某个人说的
python3 scripts/chatquery.py --who 老婆 --days 3 --json --no-ai  # 结构化，不调模型
```

| 参数 | 含义 |
|---|---|
| `--who` | 会话名模糊匹配（备注 / 昵称 / 群名），多重命中会列候选 |
| `--from` `--to` | `YYYY-MM-DD` / `MM-DD` / `今天` / `昨天` / `前天` |
| `--days` | 最近 N 天（默认 7） |
| `--by` | 只看某个发送者（`real_sender_id` 精确过滤，**默认全历史**） |
| `--ask` | 自然语言问题，走模型总结 |
| `--limit` | 取样上限（默认 4000） |
| `--show` / `--no-ai` / `--json` | 打印原文 / 不调模型 / 结构化输出 |

实现要点：`--by` 先 `select distinct real_sender_id` 再与会话成员名对齐，用 `real_sender_id` 过滤（6 万条的群也快）；AI 总结均匀抽样 90 条，要求「一句话总结 / 3-6 条要点带时间数字 / 待办待回 / 不加戏」。

### 3.2 每日日报 `wxdigest.py`（本地扩展）

```bash
python3 wxdigest.py                    # 今天
python3 wxdigest.py --date 2026-11-17
python3 wxdigest.py --push             # 推到企业微信群机器人
python3 wxdigest.py --json
```

口径：**参与 = 我在那个会话里当天发过至少一条消息**。输出分【群里】【私聊】【还没回】三段，每条给总条数、我几条、双方最后一句话。实测一天 4 个会话 / 190 条 / 5.7s。

### 3.3 增量监听 `selfnotify/watch_new.py`（本地扩展）

```bash
python3 selfnotify/watch_new.py --seed   # 记当前水位，不推送
python3 selfnotify/watch_new.py --once   # 跑一次并推送新消息
python3 selfnotify/watch_new.py          # 常驻（默认 20s 一轮）
```

- 每个会话按 `local_id` 记水位到 `state.json`，`local_id > 水位` 走主键索引（180 会话一次 union 约 0.1s）
- 过滤：自己发的不推、`filehelper` 跳过、群聊只推命中关键词的、私聊全推
- `daily.py`：当天消息量、活跃会话、Top 6、类型分布、**还没回的私聊**

---

## 4. 智能层

### 4.1 语言画像（`scripts/persona_build.py` / `persona_gen.py`）

```bash
python3 scripts/persona_build.py     # → persona/persona.json（全量统计）
python3 scripts/persona_gen.py       # → PROFILE.md + system_prompt.md + fewshot.md + examples.jsonl
```

产出四件东西：量化画像卡、可直接粘贴的 system prompt、16 组真实对话示例（8 类场景 × 2）、给模型看的「不要这样做」清单。

统计维度：句长分布、标点使用率、语气词率、连发条数、回复延迟、作息热力、高频称呼、私聊 vs 群聊差异。

### 4.2 回复风格 skill `assistant/make_skill.py`（本地扩展）

```bash
python3 assistant/make_skill.py      # → assistant/skill.md
```

从汇总库里抽「对方一句 → 我一句」的真实相邻轮次（间隔 ≤600s、我这条 2–14 字、seed 固定保证可复现），拼成 `skill.md`：任务、说话规则、场景应对表、禁止项、16 组示例、自查清单。

### 4.3 模型接入 `assistant/llm.py`（本地扩展）

- 配置优先 `assistant/config.json` 的 `llm.*`，否则读环境变量，否则扫 OpenClaw 的 provider
- 支持 OpenAI `/chat/completions` 与 Anthropic `/v1/messages` 两种端点
- **推理模型的坑**：`deepseek-v4-flash` 会把预算烧在 `reasoning_content`，`content` 为空 → 按 `finish_reason` 判断并翻倍 `max_tokens` 重试（上限 6000）；日常用 `model_fast`（`deepseek-chat`，1–5s）

### 4.4 自动回复 `assistant/autoreply.py`（本地扩展）

4 秒一拍，对开启的会话取最近 6 条：自己发的不回、超过 `max_age` 的旧消息不补、同一 `ts` 只处理一次；`dry_run` 只写 `autoreply.log`；真发走限速（45s / 每小时 12 条）。

**默认是关的**，且 `dry_run=true`——因为它要经过下面「发送」那条没打通的路。

---

## 5. 界面层

### 5.1 本地 Web 助手（`assistant/server.py`，`:8777`，本地扩展）

三栏深色界面：会话列表 / 消息流 / 助手面板。接口：

| 接口 | 作用 |
|---|---|
| `GET /api/chats` | 会话列表（含未读数、最后一条摘要） |
| `GET /api/messages?chat=&limit=&after=` | 消息增量拉取 |
| `GET /api/senders?chat=` | 该会话发送者统计（做 chips 过滤） |
| `GET /api/search?q=&chat=&days=` | 全库搜索（12 会话一批 union + 4 并发，3.1s） |
| `GET /api/summary?chat=&days=&ai=1` | 统计摘要 / 模型摘要 |
| `GET /api/suggest?chat=` | 三条候选回复 |
| `POST /api/send` | 发送（**未打通**，见 6） |
| `GET/POST /api/autoreply` | 自动回复开关 |

### 5.2 DSH 插件页面（`dsh-plugin/`，`:8778`）✅

装到 DeepSeek Harness 后，左侧栏多一个「微信记录」图标，点开是整页：

- 左栏会话列表（未读数、最后一条、时间）
- 右栏消息流（自己发的靠右、日分隔、载入更早）
- 顶部全局搜索、发送者 chips 过滤
- 右侧「AI 总结」抽屉
- 读不到服务时给「三步启动」引导，不白屏

```bash
node dsh-plugin/setup.mjs --account wxid_example_0001 --key <KEY>   # 写 ~/.dsh-wx-browser/config.json (0600)
dsh plugin install <tgz 或目录>                                      # 或用 DSH 的插件管理界面
```

服务是**内置**的：宿主 `apply()` 时自己起 `127.0.0.1:8778`，退出时 `ctx.effect` 收尾。

### 5.3 离线静态页（`export/index.html`）✅

最省事的形态：`gen_html.py` 生成的纯静态 HTML，双击即看、可离线、可发给自己。

---

## 6. 发送（❌ 三条路都没通，写清楚免得别人重踩）

| 路线 | 结果 |
|---|---|
| 系统级键鼠模拟（CGEvent / AX） | 需要「辅助功能」授权；`AXIsProcessTrusted()=0` 时所有按键静默丢弃；`osascript` 报 `-25211`。**能用，但要用户手动授权** |
| 进程内投递 NSEvent（`postEvent` / `sendEvent` / `CGEventPostToPid`，5 种通道） | 全部返回 ok，但库里的 `max(create_time)` 一次都没前进——**微信 4.2 是 Qt（`QNSWindow`/`QNSView`），不处理合成事件** |
| 改代码下断点 / 内联 hook | arm64 页 COW 后丢执行权限，进程 `SIGBUS`；硬件断点异常不投递到 task port（无 `P_TRACED`）。**不可用** |

另外：`sendmsg`(2) / `newsendmsg`(237) / `sendappmsg`(107) / `sendemoji`(68) 这些命令号能定位到，但走的是私有协议 + 服务端校验，属于违反用户协议的那条路，本仓库不做。

---

## 7. 附件（❌ 未解）

| 类型 | 现状 |
|---|---|
| 图片 `msg/attach/<md5(会话)>/YYYY-MM/Img/*.dat` | 有 `aeskey`（32 hex）但 XML 里没有本地 md5，需要密钥↔文件配对试探；AES-128-ECB 解出来应是 `FF D8 FF` / `89 50 4E 47` |
| 文件 `msg/file/YYYY-MM/<原名>` | **明文**，直接可读 |
| 视频 `msg/video/YYYY-MM/<md5>.mp4` | 明文 + 同名 `.jpg` 封面，用 XML 里的 md5 对 |
| 语音 | silk 编码，需转码 |

---

## 8. 数据与安全边界

- 所有查询都跑在 `cp -c` 克隆上，`wxq` 只读、只允许 SELECT
- 主密钥、`account_key.json`、`keys_hook.json`、`out/`、`export/` 都**不在仓库里**
- 仓库里的示例一律 `<ACCOUNT_KEY>` / `wxid_example_0001`
- 适用范围：自己机器上、自己登录的账号；不含发送、不含云端、不含他人账号
