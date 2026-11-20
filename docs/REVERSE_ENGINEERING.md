# 微信 macOS 4.2.0 逆向报告：本地数据与接口

> 目标版本：WeChat for macOS **4.2.0**（arm64，`com.tencent.xinWeChat`，Developer ID `5A4RE8SF68`）
> 报告时间：2026-11-19
> 结论一句话：**读（本地库）已完全打通并有可用工具；发（客户端内发送）只到"定位到命令号"，未做通。**

---

## 0. 能力边界

| 能力 | 状态 | 说明 |
|---|---|---|
| 解密 `db_storage/*.db` | ✅ 完整 | 拿到账号主密钥后 20 个库 100% 解开 |
| 解析消息表、会话、联系人、朋友圈 | ✅ 完整 | 单账号几十万条消息实测导出 |
| 增量监听新消息 | ✅ 可用 | APFS clone 快照 + 只读查询，不锁库、不写微信目录 |
| 定位发送协议命令号 | ⚠️ 部分 | 命令号有，protobuf 结构与调用链没有 |
| 在客户端内自动发送 | ❌ 未通 | 见 §8，三条路线全部撞墙/未完成 |

---

## 1. 落盘布局

```
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/
├── all_users/                      # 登录前的公共数据
├── wxid_<id>_<hash>/               # 每个账号一个目录（多账号不共存）
│   ├── db_storage/                 # 全部加密 .db（首 16 字节 = salt）
│   │   ├── message/message_0.db            # 消息主体，150 张 Msg_* 分表
│   │   ├── message/biz_message_0.db        # 公众号消息
│   │   ├── message/media_0.db              # 媒体索引
│   │   ├── message/message_fts.db          # 全文索引
│   │   ├── session/session.db              # 会话列表
│   │   ├── contact/contact.db              # 联系人 / 群成员
│   │   ├── sns/sns.db                      # 朋友圈
│   │   ├── favorite/ head_image/ emoticon/ ...
│   │   └── *.kvdb / *.material             # 4.2 新增：元数据 KV + 加密增量副本
│   └── msg/
│       ├── attach/<md5(会话)>/YYYY-MM/Img/*.dat   # 微信自有图片格式
│       ├── file/YYYY-MM/<原文件名>                # 明文文件
│       └── video/YYYY-MM/<md5>.mp4                # 明文视频 + .jpg 封面
```

---

## 2. 加密层（SQLCipher 4）

### 2.1 参数（实测，全部为默认值）

| 参数 | 值 |
|---|---|
| 算法 | AES-256-CBC |
| page size | 4096 |
| KDF | PBKDF2-HMAC-**SHA512**，iter=**256000** |
| HMAC | HMAC-SHA512，每页 |
| reserve | **80** 字节/页 |
| salt | 文件**前 16 字节**，每库独立 |

可用 `sqlcipher` CLI 验证参数（但不能用它解密，见 2.3）：

```bash
sqlcipher db_storage/session/session.db
sqlite> PRAGMA key = "x'<64hex raw key>'";   # 语义不对，见下
```

### 2.2 密钥语义（关键）

微信调用的是 **`sqlite3_key(db, key_ptr, 32)`**：直接传 **32 字节二进制口令**。

- 一**账号一把**密钥，账号内所有库共用；
- 每库仍有自己的 16 字节 salt（salt 参与 page 加密 key 派生，不参与口令）；
- 不同账号的密钥不通用（实测用小号 key 解大号库 → `file is not a database (26)`）。

### 2.3 三个"看起来能用其实不行"的做法

| 写法 | 结果 | 原因 |
|---|---|---|
| `PRAGMA key="x'<64hex>'"` | rc=26 | 这是 **raw key** 语义（跳过 KDF） |
| `PRAGMA key='<64hex 文本>'` | rc=26 | 这是**文本口令**语义（把 64 个字符当密码） |
| 内存里搜 `x'<key><salt>'` 99 字节串 | 0 命中 | 4.0.x 才有这种传参，4.2 已改为二进制 |

**唯一正确的解密方式**（C/ctypes 均可）：

```c
int sqlite3_key(sqlite3*, const void*, int);   // 需手写声明，头文件不导出
sqlite3_key(db, key32, 32);                    // key32 = 32 字节原始二进制
```

---

## 3. 密钥获取（可复现）

### 3.1 失败路线（记录一下，避免重复踩）

| 路线 | 结果 |
|---|---|
| 内存字符串搜 `x'<key+salt>'` | 0 候选（4.2 不存在该形态） |
| 内存搜 salt（hex 文本） | 0 命中；二进制形式只在**已打开**的库附近出现 |
| 硬件断点（`ARM_DEBUG_STATE64`） | kr=0 写入成功，但无 `P_TRACED` 时异常不投递，目标直接 SIGTRAP 死亡 |
| `ptrace(PT_ATTACH)` + 软件断点 | attach 成功，但给 `__TEXT` 打进 `brk #0` 后 COW 页丢执行权限 → **SIGBUS**（arm64 代码签名挡住"改码再执行"） |
| 共享缓存页 `mach_vm_write` | P_TRACED 下可以写，但同样执行即崩 |

### 3.2 成功路线：dyld interpose 拦 `CCKeyDerivationPBKDF`

`CCKeyDerivationPBKDF` 的真实签名比 SDK 头文件**多一个首参**：

```c
int CCKeyDerivationPBKDF(CCPBKDFAlgorithm algorithm,      // x0, 2 = kCCPBKDF2
                         const char *password, size_t passwordLen,  // x1, x2
                         const uint8_t *salt,  size_t saltLen,      // x3, x4
                         CCPseudoRandomAlgorithm prf,               // x5, 5 = SHA512
                         unsigned rounds,                           // x6, 256000
                         uint8_t *derivedKey, size_t derivedKeyLen);// x7, x8
```

必须**自签微信副本**（原版有 hardened runtime 且无 `disable-library-validation`）：

```bash
cp -cR /Applications/WeChat.app ./WeChatHook.app
# entitlements = 原有全部 + disable-library-validation + allow-dyld-environment-variables
codesign -f -s - --entitlements ./ent_wx.plist WeChatHook.app/Contents/MacOS/WeChat
DYLD_INSERT_LIBRARIES=./wxhook.dylib ./WeChatHook.app/Contents/MacOS/WeChat
```

dylib 核心（`wxhook_dylib.c`）：

```c
static const struct { const void *replacement, *replacee; } interposers[]
  __attribute__((section("__DATA,__interpose"))) __attribute__((used)) = {
    { (const void *)my_pbkdf, (const void *)CCKeyDerivationPBKDF } };
/* 真函数 = interposers[0].replacee，不会被 dyld 重绑 */
```

抓到的即 `password`（32B，就是主密钥）、`salt`（16B）。**筛选条件：`rounds == 256000 && prf == 5 && passwordLen == 32`**，其余（rounds=2、salt=`af6e9c51…`）是微信自己的二级派生，不是库密钥。

### 3.3 自动化收敛

`watch_key.py`：边抓边试——用候选 key 解目标账号 `session.db` 的副本，成功即判定命中并落盘 `account_key.json`。实测切换账号后 **72 秒**内自动抓到。

---

## 4. 库表结构

### 4.1 消息表（`message_0.db`）

**分表规则：`Msg_<md5(会话 username)>`**。例：

```python
"filehelper"        -> Msg_9e20f478899dc29eb19741386f9343c8
"1747540946@chatroom" -> Msg_06253a6da34461adde81ff87b44dfab1
```

```sql
CREATE TABLE Msg_<md5>(
  local_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 会话内自增，可当消息序号
  server_id INTEGER, local_type INTEGER, sort_seq INTEGER,
  real_sender_id INTEGER,        -- → Name2Id.rowid
  create_time INTEGER,           -- 秒级 Unix 时间戳
  status INTEGER, upload_status INTEGER, download_status INTEGER,
  server_seq INTEGER, origin_source INTEGER, source TEXT,
  message_content TEXT,          -- 正文（可能被 zstd 压缩）
  compress_content TEXT, packed_info_data BLOB,
  WCDB_CT_message_content INTEGER,  -- 0=明文, 4=zstd
  WCDB_CT_source INTEGER
);
```

发送者映射：`Name2Id(user_name TEXT PRIMARY KEY, is_session INTEGER)` 的 **rowid ↔ `real_sender_id`**。

### 4.2 会话表（`session.db`）

```sql
CREATE TABLE SessionTable(
  username TEXT PRIMARY KEY, type INTEGER,
  unread_count INTEGER, summary TEXT, draft TEXT, status INTEGER,
  last_timestamp INTEGER, sort_timestamp INTEGER,
  last_msg_locald_id INTEGER, last_msg_type INTEGER, last_msg_sender TEXT,
  last_sender_display_name TEXT, ...);
```

`type` 粗分类：`@chatroom` 结尾为群，`gh_` 开头为公众号，其余为个人。（公众号会话**没有** `Msg_` 分表，查会报 `no such table`，需跳过。）

### 4.3 联系人（`contact/contact.db`）

```sql
CREATE TABLE contact(
  id INTEGER PRIMARY KEY, username TEXT, local_type INTEGER,
  alias TEXT, encrypt_username TEXT, remark TEXT, nick_name TEXT,
  pin_yin_initial TEXT, quan_pin TEXT, description TEXT, ...);
CREATE TABLE chatroom_member(...);   -- 群成员
CREATE TABLE chat_room(...);         -- 群信息
```

显示名优先级：`remark` → `nick_name` → `alias` → `username`。

### 4.4 朋友圈（`sns/sns.db`）

`SnsTimeLine(tid, user_name, content, pack_info_buf)`，`content` 为 XML，图片/位置在 `pack_info_buf`（注意 `text_factory=bytes` 读二进制）。

---

## 5. 消息编码

### 5.1 正文格式

```
<发送者username>:\n<body>
```

- 群聊：`发送者` 是群成员 wxid；
- 单聊：`发送者` 是自己或对方 wxid（配合 `real_sender_id` 双重确认）。

`body` 按 `local_type` 是纯文本或 XML：

```xml
<!-- 应用消息 <appmsg> -->
<title>标题</title><des>描述</des><type>57</type><url>...</url>
<!-- 图片 <img aeskey=".." cdnthumburl=".." md5=".."> -->
<!-- 语音 <voicemsg voicelength=".." /> / 视频 <videomsg md5=".."/> -->
```

### 5.2 压缩

`WCDB_CT_message_content = 4` 时，`message_content` 是 **zstd** 帧（magic `28 B5 2F FD`）：

```python
ctypes.CDLL("/opt/homebrew/lib/libzstd.1.dylib")   # 见 zstdlib.py
```

### 5.3 `local_type` 映射（实测）

| 值 | 含义 |
|---|---|
| 1 | 文本 |
| 3 | 图片 |
| 34 | 语音 |
| 43 | 视频 |
| 47 | 表情（sticker） |
| 48 | 位置 |
| 49 | 应用消息（链接/文件/引用/小程序…） |
| 50 | 通话 |
| 10000 | 系统消息（入群提示等） |

应用消息是**高位变体**：取 `base = local_type & 0xFFFFFFFF`，`base == 49` 即应用消息，高位区分具体卡片：

| 原始值 | 含义 |
|---|---|
| 244813135921 | 引用/转发类 |
| 266287972401 | 拍一拍 |
| 141733920817 | 视频号/直播卡片 |
| 8589934592049 | 转账 |

> 判类型别用 `==`，用 `& 0xFFFFFFFF`。

---

## 6. 附件

| 类型 | 路径 | 状态 |
|---|---|---|
| 文件 | `msg/file/YYYY-MM/<原名>` | ✅ 明文，直接读 |
| 视频 | `msg/video/YYYY-MM/<md5>.mp4` | ✅ 明文，`md5` 与 XML 里的 `md5` 对应 |
| 图片 | `msg/attach/<md5(会话)>/YYYY-MM/Img/*.dat` | ❌ 未解 |
| 语音 | 同上 `Audio/*.silk` | ❌ 未解（silk 编码，需转码） |

`.dat` 头部固定 `07 08 56 32 08 07 00 04 …`（`\x07\x08V2`）。图片消息 XML 里有 `aeskey`（32 hex），但 **本地 `.dat` 文件不带自己的 md5**，两者需要"用 aeskey 试解候选文件、验 `FF D8 FF` / `89 50 4E 47` 魔数"来配对。这条路没走完。

---

## 7. 收发协议层（发送侧现状）

### 7.1 客户端结构

- `wechat.dylib` ≈ 340 MB，**导出符号基本剥离**（`_OBJC_CLASS_*` 为 0），核心是 C++（命名空间 `mmui::`）；
- UI 是 **Qt**：窗口类 `QNSWindow` / `QNSView` / `TUINSWindow` / `FlueUniversalWindow`，内容自绘（`cacheDisplayInRect` 截图为全白，Metal）；
- 二进制字符串表里可定位到 CGI 命令号：

| 命令 | 号 |
|---|---|
| `sendmsg` | 2 |
| `newsendmsg` | 237 |
| `sendappmsg` | 107 |
| `sendemoji` | 68 |

### 7.2 为什么没做通

| 路线 | 结果 |
|---|---|
| hook 内部发送函数（断点/改码） | arm64 代码签名挡住，见 §3.1 |
| 进程内合成 UI 事件（`postEvent:` / `sendEvent:` / `CGEventPostToPid`，5 种通道） | 全部返回成功，但 Qt **不处理**合成事件，库里 `create_time` 不动 |
| 系统级键盘模拟（辅助功能） | 技术可行，但需要用户手动授权 AX，且属于"操作你的电脑" |
| 协议层（自己构造 protobuf 走长连接） | **未做**。缺：protobuf schema、密钥协商、会话态。工作量大且随版本失效 |

### 7.3 如果要做通，需要什么

1. 用 Frida/LLDB 在 `wechat.dylib` 里定位 `sendmsg(2)` 的请求构造点（需先解决 arm64 改码限制，或改用 `DYLD_INSERT_LIBRARIES` + `__interpose` 拦截其序列化函数）；
2. dump protobuf descriptor；
3. 复用已有的登录态与长连接（不能自己另起连接，必须搭在客户端现成的通道上）。

---

## 8. 工具清单（都在本目录）

| 工具 | 用途 |
|---|---|
| `wxhook.dylib` + `wxhook_dylib.c` | interpose `CCKeyDerivationPBKDF`，抓 32B 主密钥 |
| `watch_key.py` | 边抓边试，自动确认密钥并写 `account_key.json` |
| `wxq` | **推荐**：带 key 打开加密库跑 SQL，输出 TSV，BLOB 输出 `0x<hex>` |
| `wxdec` | 用 `ATTACH … KEY ''` + `sqlcipher_export()` 把加密库导出成明文库 |
| `wxsql` | 带 key 打开并执行 SQL（调试用） |
| `export.py` | 批量快照 + 解密 `db_storage` → `out/<账号>/` |
| `build_export.py` | 解析分表/压缩/XML → `export/wechat.db`（messages/chats/contacts/moments） |
| `gen_html.py` / `gen_moments.py` | 生成可浏览页面 + `search.html` |
| `serve.py` | 本地检索服务（127.0.0.1:8765，`/api/search?q=`） |
| `zstdlib.py` | zstd 解压（ctypes 调 libzstd） |
| `persona_build.py` / `persona_gen.py` / `make_viz.py` | 语言风格画像与可视化页 |
| `src/wxr/watcher.py` / `notify.py` / `digest.py` | 新消息监听 + 通知 + 日报 |
| `wxdigest.py` | 按"我参与过"生成日报 |
| `assistant/` | 本地 Web 助手（会话列表/消息流/总结/建议/自动回复引擎） |

失败路线的源码保留：`scan_keys.c`、`memgrep.c`、`keytest.c`、`dumpregion.c`、`bp.c`、`ptest.c`、`ptry.c`、`wxhook.c`、`wxsend.m`、`wxagent.m`。

---

## 9. 复现步骤

```bash
# 1. 抓密钥（一次性，需要跑改签副本并登录）
./wxhook.dylib ...                      # 见 §3.2
python3 watch_key.py                    # 自动确认并写 account_key.json

# 2. 解一个库看看
./wxq "$DB" "$(python3 -c 'import json;print(json.load(open("account_key.json"))["key"])')" \
  "select count(*) from sqlite_master"

# 3. 全量导出
python3 export.py                       # → out/<账号>/
python3 build_export.py                 # → export/wechat.db
python3 gen_html.py && python3 serve.py

# 4. 增量监听（只读、不锁库）
wxr watch --seed
wxr watch
```

---

## 10. 边界与风险

- **仅限本机、本人账号、本人数据**。密钥绑定账号，跨账号无效。
- 抓密钥需要**改签客户端副本**（`disable-library-validation`），这会降低该副本的完整性保护；用完请换回 `/Applications/WeChat.app`。
- 本报告**不包含**任何绕过登录、伪造身份、克隆他人语气的能力。
- 客户端自动发送违反微信用户协议，有封号风险；本报告只描述接口现状，不提供可用发送实现。
- 版本敏感：`4.2.0` 实测有效；微信升级后库结构、密钥派生、命令号都可能变化。
