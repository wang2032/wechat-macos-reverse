# 功能详解

这份文档回答「这个仓库到底能做什么、每个能力怎么用、哪些做不到」。

图例：✅ 可用　🟡 有代码但需要你补配置（密钥 / 模型 / 授权）　❌ 没做通

## 一、能力总表

| # | 能力 | 入口 | 状态 |
|---|---|---|---|
| 1 | 抓账号主密钥（每账号一次） | `make tools` + `build/wxhook.dylib` | 🟡 |
| 2 | 只读查询加密库 | `build/wxq`（`wxr core` 内部用） | ✅ |
| 3 | 整库解密 | `wxr export` → `build/wxdec` | 🟡 |
| 4 | 会话 / 消息 / 发送者 / 搜索 | `wxr chats` / `messages` / `search` | 🟡 |
| 5 | 全量汇总成单文件 SQLite | `wxr export` | 🟡 |
| 6 | 可离线浏览的聊天网页 / 朋友圈页 | `wxr html` | 🟡 |
| 7 | 本地 HTTP 界面（浏览 / 总结 / 草稿） | `wxr web` → `:8777` | 🟡 |
| 8 | 按「谁 + 时间 + 谁说的」查记录并总结 | `wxr ask` | 🟡 |
| 9 | 某天「我参与过」的日报 | `wxr digest` | 🟡 |
| 10 | 增量监听新消息 + 通知 | `wxr watch` | 🟡 |
| 11 | 语言画像（说话风格量化 + 可视化页） | `wxr persona --viz` | 🟡 |
| 12 | 回复风格 skill（喂给模型） | `wxr skill` | 🟡 |
| 13 | 自动回复引擎（默认关、dry-run、限速） | `wxr web` + `autoreply.py` | 🟡 |
| 14 | DSH 插件页面（侧栏「微信记录」） | `plugins/dsh/` → `:8778` | 🟡 |
| 15 | OpenClaw 工具 `wx_chat` / `wx_digest` | `integrations/openclaw/` | 🟡 |
| 16 | 静态搜索服务 | `wxr serve` → `:8765` | 🟡 |
| 17 | 在微信里替人发消息 | `experiments/send/` | ❌ |
| 18 | 解密图片 / 语音 / 视频附件 | — | ❌ |
| 19 | Windows / 手机端 | — | ❌ |

🟡 的含义都一样：**代码齐全，缺的是你自己机器上的东西**——密钥（1）、编译产物（2/3）、模型 API（8/12/13 的 AI 部分）。没有密钥时除 `wxr status` 外的命令都会给出明确提示。

---

## 二、基础层

### 2.1 抓密钥（`tools/wxhook_dylib.c`）🟡

微信启动时会把主密钥交给 `CCKeyDerivationPBKDF` 派生 SQLCipher 口令。我们在自己重签的副本里 interpose 这个函数，把入参写日志：

```bash
make tools                                  # 产出 build/wxhook.dylib（arm64e + 自签）
cp -cR /Applications/WeChat.app ./WeChatHook.app
codesign -f -s - --entitlements docs/entitlements.wx.plist ./WeChatHook.app/Contents/MacOS/WeChat
DYLD_INSERT_LIBRARIES=$PWD/build/wxhook.dylib ./WeChatHook.app/Contents/MacOS/WeChat
```

日志里 `rounds=256000` 的那行 `pw` 就是主密钥。完整步骤与前置条件见 [`USAGE.md`](USAGE.md)。

> 一旦失败就退回官方 App：`osascript -e 'quit app "WeChat"' && open -a /Applications/WeChat.app`。改签副本只用来抓一次密钥。

### 2.2 只读查询（`tools/wxq.c`）✅

```bash
build/wxq <db> <64位keyhex> "select count(*) from sqlite_master"
```

- 打开方式是 `SQLITE_OPEN_READONLY`；
- prepare 之前拒绝非 `select` 语句（返回码 6，`readonly: only SELECT is allowed`）；
- 输出 TSV，BLOB 打成 `0x<hex>`，对 NUL 与制表符/换行做了转义。

### 2.3 解密（`tools/wxdec.c`）🟡

```bash
build/wxdec in.db <keyhex> out.db     # 返回码 3=open 4=key 5=attach 6=export
```

原理是 `ATTACH DATABASE 'out.db' AS p KEY ''` + `select sqlcipher_export('p')`。
`sqlite3_backup_*` 在加密库上不可用（`backup is not supported with encrypted databases`）。

---

## 三、数据层

### 3.1 全量导出（`wxr export`）🟡

```bash
wxr export                  # 两个阶段：解密 + 建汇总库
wxr export --no-build       # 只解密到 out/<账号>/
```

- 阶段一：把 `db_storage/**/*.db`（连同 `-wal`/`-shm`）拷到 `work/<账号>/`，逐库解密到 `out/<账号>/`；
- 阶段二：读 `out/` 里的明文库，产出 `export/wechat.db`。

### 3.2 汇总库结构（`export/wechat.db`）

| 表 | 主要列 |
|---|---|
| `messages` | `id, chat, local_id, ts, sender, sender_name, direction, raw_type, type, text` |
| `chats` | `username, name, kind, msg_count, first_ts, last_ts, summary` |
| `contacts` | `username, display, nick, remark, alias, kind` |
| `moments` | `ts, user, name, text, images, loc` |

```sql
-- 最近 7 天每个会话多少条
select chat, count(*) c from messages where ts > strftime('%s','now','-7 day') group by chat order by c desc;
-- 某人发过的所有链接
select ts, text from messages where sender_name like '%老张%' and text like '%http%' order by ts desc limit 20;
```

**验证**：单账号几十万条消息、上百个会话、数千联系人可以完成抽取与渲染（数量级随账号不同，不作为性能承诺）。

### 3.3 静态页面（`wxr html`）🟡

```bash
wxr html              # export/index.html + export/chats/*.html + chats.json
wxr html --no-moments # 跳过朋友圈页
```

页面是纯静态 HTML，无外部请求、无 JS 依赖，`open export/index.html` 即可。

### 3.4 搜索服务（`wxr serve`）🟡

```bash
wxr serve             # http://127.0.0.1:8765/search.html
```

Node/Python 标准库起的本地服务，`/api/search?q=&limit=` 走 `LIKE`，返回可跳转的会话文件与消息锚点。

---

## 四、查询与节奏层

### 4.1 按人 + 时间查（`wxr ask`）🟡

```bash
wxr ask --who "老婆" --days 3
wxr ask --who 羽毛球 --from 2026-11-01 --to 2026-11-18
wxr ask --who 老张 --yesterday --ask "他到底想约哪天"
wxr ask --who 项目群 --by 老王                 # 只看某个人说的
wxr ask --who 老婆 --days 3 --json --no-ai    # 结构化，不调模型
```

- `--who` 支持备注 / 昵称 / 群名，模糊匹配；命中多个会列候选；
- `--by` 用 `real_sender_id` 精确过滤，六万条的群也很快；默认查全部历史；
- 有模型时输出「一句话总结 / 分条要点 / 待回事项」，没有模型时退回本地统计。

### 4.2 每日日报（`wxr digest`）🟡

```bash
wxr digest                       # 今天
wxr digest --date 2026-11-17
wxr digest --push                # 额外推到企业微信群机器人（需配置 webhook）
wxr digest --json
```

口径是**「我参与过」**：只算当天我在里面发过言的会话。输出三段：【群里】【私聊】【还没回】。
落在 `data/digest/YYYY-MM-DD.txt`（已在 `.gitignore` 里）。

### 4.3 增量监听（`wxr watch`）🟡

```bash
wxr watch --seed   # 记当前水位，不推送
wxr watch --once   # 跑一次并推送新消息
wxr watch          # 常驻（默认 20s 一轮）
```

- 每个会话按 `local_id` 记水位到 `~/.cache/wxr/watch_state.json`，查 `local_id > 水位` 走主键；
- 自己发的、`filehelper` 不发通知；群聊按关键词过滤（配置 `groups.keywords`），私聊全推；
- 通知通道见 `src/wxr/notify.py`：`macos`（系统通知）、`wecom`（企微群机器人）、`inbox`（追加 markdown）、`stdout`。

### 4.4 当日统计（`wxr daily`）🟡

收发条数、活跃会话、Top 会话、类型分布、**还没回的私聊**（最后一条是对方发的纯文本、2 小时–7 天内没回）。

---

## 五、智能层

### 5.1 语言画像（`wxr persona`）🟡

```bash
wxr persona          # data/persona/persona.json + PROFILE.md + fewshot.md + examples.jsonl
wxr persona --viz    # 额外生成 data/persona/index.html 可视化页
```

统计的是「我」发出的文本：句长分布、标点使用率、语气词、连发节奏、回复延迟、作息热力、口头禅。
`system_prompt.md` 可以直接粘给任何模型当人设。

### 5.2 回复 skill（`wxr skill`）🟡

```bash
wxr skill            # 从汇总库抽真实轮次，写 ~/.cache/wxr/skill.md
```

抽取条件是「对方一句 → 我一句」的相邻轮次（间隔 ≤600s、我这条 2–14 字），生成 16 组示例 + 说话规则表。
`wxr ask` / 自动回复都拿它当 system prompt；改说话风格直接改这个文件。

### 5.3 模型配置（`src/wxr/llm.py`）🟡

优先级：`~/.cache/wxr/config.json` 的 `llm` 段 → `DEEPSEEK_API_KEY` → OpenClaw 里第一个可用 provider。

```json
{
  "llm": {
    "api": "openai",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "model_fast": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY"
  }
}
```

兼容 Anthropic 的 `/v1/messages` 与 OpenAI 的 `/chat/completions`；推理模型把预算烧在 `reasoning_content` 导致正文为空时会自动翻倍重试。模型不可用时所有 AI 功能退回本地规则。

### 5.4 自动回复（`src/wxr/autoreply.py`）🟡

**默认关闭、`dry_run: true`、限速 45 秒 / 每小时 12 条**，且只在有发送能力时才真的发；否则只写 `~/.cache/wxr/autoreply.log`。

```json
{ "autoreply": { "enabled": false, "dry_run": true, "chats": [], "min_gap": 45, "max_per_hour": 12, "max_age": 600 } }
```

现实提醒：本仓库的发送能力是 ❌，所以它实际只能产出草稿（写日志 + 在界面上给建议）。要真的发，看 [`../experiments/send/README.md`](../experiments/send/README.md) 的结论。

---

## 六、界面层

### 6.1 本地 Web 界面（`wxr web`，`:8777`）🟡

```bash
wxr web                    # http://127.0.0.1:8777
wxr web --port 8799
```

三栏布局：会话列表 / 消息流 / 助手面板。能力：会话与消息浏览（2 秒轮询增量）、全局搜索、发送者筛选、AI 总结、回复建议、草稿、自动回复开关。

### 6.2 DSH 插件（`plugins/dsh/`，`:8778`）🟡

DeepSeek Harness 侧栏里的一整页「微信记录」。

```bash
node plugins/dsh/setup.mjs --account <账号> --key <KEY>   # 写 ~/.dsh-wx-browser/config.json (0600)
dsh plugin install ./plugins/dsh                          # 或装 npm pack 出来的 tgz
```

宿主侧 `index.js` 起本地服务；客户端 `client.js` 注册 `main` 页面与 `sidebar.panellist` 图标。不用 Python、不用 brew —— 服务是 Node 标准库，查询走静态链接的 `plugins/dsh/bin/wxq`。

### 6.3 OpenClaw 工具（`integrations/openclaw/`）🟡

```bash
openclaw plugins install ./integrations/openclaw/wxchat --link --dangerously-force-unsafe-install
openclaw plugins install ./integrations/openclaw/wxdigest --link --dangerously-force-unsafe-install
```

产出 `wx_chat`（按人查记录）与 `wx_digest`（日报）两个工具。`child_process` 会触发安装扫描，所以需要 `--dangerously-force-unsafe-install`；`--link` 是为了保留相对路径。

---

## 七、做不到的部分

| 想做的事 | 结论 |
|---|---|
| 在微信里替人发消息 | ❌ 三条路都试过：AX 模拟按键、注入投递 NSEvent/CGEvent、协议层 `sendmsg`。前两条被「需要用户授权」和「Qt 不处理合成事件」挡住，第三条违协议 |
| 看图片原图 | ❌ `.dat` 是加密的，图片消息 XML 里有 `aeskey` 但没有本地 md5，配对关系没破 |
| 听语音 | ❌ silk 编码，且同样在加密容器里 |
| 看视频原片 | 🟡 `msg/video/**/*.mp4` 是明文按 md5 命名，能对上消息里的 md5，但消息里不一定带 md5 |
| Windows / 安卓 | ❌ 加密参数、库结构、UI 栈都不同 |

---

## 八、安全边界

- 只读：`wxq` 强制 `READONLY` + 只允许 `SELECT`；所有查询都在 `cp -c` 克隆上跑。
- 不联网：除你自己配置的模型 API 之外没有出网请求。
- 密钥：只在运行时出现，不写日志、不进仓库。仓库里所有示例都是 `wxid_example_0001` / `<KEY>`。
- 用途：只处理你自己的设备与账号。
