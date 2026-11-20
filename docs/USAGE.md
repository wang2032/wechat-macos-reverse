# 使用说明

假设你在自己的 Mac 上，微信 4.1/4.2 已登录，想把这些记录变成能查、能导、能总结的数据。

> 全程只读。所有查询跑在 APFS 克隆出来的副本上，不写微信目录、不碰运行中的文件句柄。
> 你的数据只在这台机器上，唯一会读到聊天内容的「外部」是你自己配的模型。

---

## 第一步：拿到你账号的主密钥（只要一次）

微信用 SQLCipher 加密每个库，**每个账号一把 32 字节主密钥**，账号内所有库共用。密钥不落盘，只在运行时存在，所以得从进程里抓。

```bash
# 1) 检查前提
csrutil status                      # 必须是 disabled
codesign -dv /Applications/WeChat.app 2>&1 | grep -E "Authority|flags"

# 2) 编译抓钥 dylib（必须 arm64e）
cc -O2 -arch arm64e -dynamiclib -o build/wxhook.dylib tools/wxhook_dylib.c -framework CoreFoundation
codesign -f -s - build/wxhook.dylib

# 3) 复制一份微信，加两个 entitlement 后重签
cp -cR /Applications/WeChat.app build/WeChatHook.app
codesign -f -s - --entitlements docs/entitlements.wx.plist.example \
  build/WeChatHook.app/Contents/MacOS/WeChat

# 4) 带着 dylib 启动副本，登录你的账号
osascript -e 'quit app "WeChat"'
DYLD_INSERT_LIBRARIES=$PWD/build/wxhook.dylib \
  build/WeChatHook.app/Contents/MacOS/WeChat > /tmp/wxhook.log 2>&1 &

# 5) 登录后从日志里取 rounds=256000 的那把 key
grep 'rounds=256000' /tmp/wxhook.log | head
```

拿到形如 `pw=<64位十六进制>` 的那串，记成 `KEY`。用 `wxq` 验证一下：

```bash
DB="$HOME/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号>/db_storage/session/session.db"
./bin/wxq "$DB" "$KEY" "select count(*) from sqlite_master"   # 出数字就成了
```

> 抓完把副本退出、换回官方 `/Applications/WeChat.app`，别再让改签版跑着。
> 密钥丢了也不用慌：重走一遍第 4 步即可（密钥本身不变）。

---

## 第二步：选一个你用得上场景

### 场景 A：我就想查「某人上周说了什么」

```bash
python3 scripts/chatquery.py --who "老婆" --days 7
python3 scripts/chatquery.py --who "羽毛球" --yesterday --ask "最后定的是几点"
python3 scripts/chatquery.py --who "项目群" --by 老王 --from 2026-10-20 --to 2026-11-15
```

`--who` 支持备注、昵称、群名的模糊匹配，命中多个会列出来让你选。加 `--json` 可以喂给别的脚本。

### 场景 B：我想把全部记录导出来自己分析

```bash
python3 scripts/export.py --account <账号> --key "$KEY"    # 解出 out/<账号>/*.db
python3 scripts/build_export.py                            # 汇成 export/wechat.db
python3 scripts/gen_html.py                                # 生成可离线浏览的网页
open export/index.html
```

`export/wechat.db` 里就四张表（`messages` / `chats` / `contacts` / `moments`），随便拿 SQLite 工具查：

```sql
select date(ts,'unixepoch','localtime') d, count(*) n
from messages where direction='out' group by d order by d desc limit 10;

select chat, text, datetime(ts,'unixepoch','localtime')
from messages where text like '%合同%' order by ts desc limit 20;
```

### 场景 C：我想每天收一份「今天我聊了啥」

```bash
python3 wxdigest.py                       # 今天的日报，打印
python3 wxdigest.py --date 2026-11-19     # 昨天
python3 wxdigest.py --json                # 结构化，给 agent 二次加工
```

口径是「我参与过」——当天我在这个会话里发过言才算。输出分【群里】【私聊】【还没回】。

想让它自己每天跑：`cron` 或 `openclaw cron add --name wx-digest --cron "0 21 * * *" --tz Asia/Shanghai ...`。

### 场景 D：我想在 DSH 里点开就看

```bash
node dsh-plugin/setup.mjs --account <账号> --key "$KEY"
dsh plugin install ./dsh-plugin          # 或用插件管理界面装 tgz
```

装完刷新 DSH 页面，左侧栏出现「微信记录」：左栏会话、右栏消息、顶部搜索、发送者过滤、AI 总结抽屉。

页面自带服务（`127.0.0.1:8778`），不用另开进程；端口冲突用 `WX_BROWSER_PORT` 改。

### 场景 E：我想让 AI 学我说话

```bash
python3 scripts/persona_build.py     # 统计：句长/标点/语气词/连发/延迟/作息
python3 scripts/persona_gen.py       # → persona/system_prompt.md（直接粘给模型用）
python3 assistant/make_skill.py      # → assistant/skill.md（当 system prompt 更完整）
```

`system_prompt.md` 是给通用模型用的；`skill.md` 更结构化，适合 OpenClaw / Claude Code 这类能装 skill 的宿主。

---

## 常见报错

| 报错 | 原因 | 处理 |
|---|---|---|
| `file is not a database (26)` | key 不对；或对明文库传了 key；或库被微信「工厂化」换钥了 | 换正确的 key；明文库不要传 key；见 `docs/RECOVERY.md` |
| `prepare rc=26` | 同上 | 同上 |
| `backup is not supported with encrypted databases` | 用了 `sqlite3_backup_*` | 改用 `ATTACH ... KEY ''` + `sqlcipher_export` |
| `have 'arm64', need 'arm64e'` | dylib 架构不对 | 编译加 `-arch arm64e` |
| 日志里没有 `rounds=256000` | dylib 没加载进主进程；或还没登录；或被 helper 进程抢了 | 检查 `hasSuffix:@"/Contents/MacOS/WeChat"` 判定、确认已登录、看 `/tmp/wxhook.log` |
| 卡片消息全是 `[卡片消息]` | Python 缺 `expat`，XML 解析静默失败 | 用正则解析，或装完整 Python |
| 搜不到 `Msg_xxx` 表 | 公众号会话（`gh_` 开头）没有消息分表 | 正常，跳过 |
| DSH 页面白屏 | 服务没起来 / 端口被占 | `curl 127.0.0.1:8778/api/health`，或换 `WX_BROWSER_PORT` |
| 历史记录突然没了 | 微信检测到异常把库 `.factory` 化并换钥 | 见 `docs/RECOVERY.md`，用最近的克隆回填 |

---

## 数据在哪

```
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号>/
├── db_storage/           20 个加密库（message/session/contact/sns/favorite/…）
├── msg/attach/<md5(会话)>/YYYY-MM/Img/*.dat    图片（加密，未解）
├── msg/file/YYYY-MM/                           文件（明文）
└── msg/video/YYYY-MM/<md5>.mp4                 视频（明文）
```

表名映射：会话 `username` → `Msg_<md5(username)>`，例 `1747540946@chatroom` → `Msg_06253a6da34461adde81ff87b44dfab1`。
发送者：`Msg_*.real_sender_id` ↔ `Name2Id` 的 rowid ↔ `Name2Id.user_name`。

---

## 边界

- 只处理**自己账号**、本机数据
- 不含发送、不含协议层调用、不含云端接口
- 解密后的数据是你的隐私：别提交进 git，别传到公共网盘
- 改签副本记得删，用完换回官方客户端
