# 微信 macOS 4.2 本地数据逆向工具集

在 **macOS + 微信 4.2.0（arm64）** 上，把本地 `db_storage/` 里加密的聊天记录解开，变成可查询、可导出的数据。包含：抓密钥的注入库、只读查询/解密工具、导出脚本、以及一个 DeepSeek Harness 插件页面。

> 目标版本：WeChat for macOS **4.2.0**（`com.tencent.winWeChat`，Developer ID `5A4RE8SF68`）

---

## ⚠️ 先读这一段

- 这套东西**只对你自己这台机器、你自己登录的账号**有意义。不要拿去读别人的设备。
- 仓库里**不含任何真实密钥、账号 wxid 或聊天内容**，占位符（`<ACCOUNT_KEY>`、`wxid_example_0001`）都要你用自己的替换。
- 解密出来的是最私密的数据，**不要提交进 git、不要上传网盘**。`.gitignore` 已经挡掉了常见数据目录，但请自己再看一眼。
- 本仓库**不含发送能力**。原因见 [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md) §8：个人微信没有官方发送接口，三条路线（辅助功能注入 / 内存打补丁 / 进程内事件投递）实测全部撞墙。要做自动化发消息，走企业微信自建应用或公众号，别碰协议。

---

## 能力边界

| 能力 | 状态 | 说明 |
|---|---|---|
| 抓账号主密钥 | ✅ | 自签副本 + `__interpose` 拦 `CCKeyDerivationPBKDF` |
| 解密 `db_storage/*.db` | ✅ | SQLCipher4：AES-256-CBC / PBKDF2-HMAC-SHA512 256000 / page 4096 |
| 消息 / 会话 / 联系人 / 朋友圈 | ✅ | 实测单账号 42 万条消息、180 会话、8000 联系人、2300 朋友圈 |
| 增量监听新消息 | ✅ | APFS clone 快照 + 只读查询，不锁库、不写微信目录 |
| 在客户端里发消息 | ❌ | 见 §8 |
| Windows / 手机端 | ❌ | 参数与布局完全不同，没做 |

---

## 工作链路

```
                 ┌──────────────────────────────┐
  WeChat.app ──▶ │ wxhook.dylib（__DATA,__interpose）│ ──▶ pw + salt（KDF 入参）
                 └──────────────────────────────┘
                              │
                              ▼
              wxq / wxdec ──▶ SQLCipher 解密 ──▶ 明文 SQLite
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        chatquery.py     export.py      dsh-plugin（网页）
        按人/按时间查     全量导出        DSH 左侧栏一页
```

关键点：微信在**运行时**用 `sqlite3_key(db, key, 32)` 把 32 字节主密钥交给 SQLCipher，这个 key 是**账号级**的（同账号所有库共用，每库各有自己的 16 字节 salt），不落盘、不走 `x'<key><salt>'` 字符串。所以必须从 `CCKeyDerivationPBKDF` 的入参里拿。

---

## 快速开始

### 1. 编工具

```bash
# 静态链接版（不需要装 sqlcipher，产物体积 5.5MB）
brew install sqlcipher openssl@3      # 只在编译时需要
cc -O2 -o bin/wxq tools/wxq.c \
   "$(brew --prefix sqlcipher)/lib/libsqlcipher.a" \
   "$(brew --prefix openssl@3)/lib/libcrypto.a" \
   -framework Security -framework CoreFoundation -lz

# 或者动态链接（本机装了 sqlcipher 即可）
cc -O2 -I"$(brew --prefix sqlcipher)/include" -o wxq tools/wxq.c \
   -L"$(brew --prefix sqlcipher)/lib" -lsqlcipher
```

完整编译说明见 [`docs/BUILD.md`](docs/BUILD.md)。

### 2. 抓密钥（一次性，每账号一次）

```bash
# 复制一份微信、加两个 entitlement 后 ad-hoc 重签
cp -cR /Applications/WeChat.app ./WeChatHook.app
codesign -f -s - --entitlements entitlements.plist WeChatHook.app/Contents/MacOS/WeChat

# 编译注入库（必须 arm64e，与主程序架构一致）
cc -O2 -dynamiclib -arch arm64e -o wxhook.dylib tools/wxhook_dylib.c -framework CoreFoundation
codesign -f -s - wxhook.dylib

# 带着 dylib 启动，登录目标账号，日志里就出现 pw（32 字节 hex）
DYLD_INSERT_LIBRARIES=$PWD/wxhook.dylib ./WeChatHook.app/Contents/MacOS/WeChat
```

`entitlements.plist` = 微信原有 entitlements + `com.apple.security.cs.disable-library-validation` + `com.apple.security.cs.allow-dyld-environment-variables`，重签时**不要加** `--options runtime`。

日志里 `rounds=256000` 的那条就是 SQLCipher 口令：

```
PBKDF2 alg=2 pwlen=32 saltlen=16 prf=5 rounds=256000 caller=0x... pw=<64位hex> salt=<32位hex> dk=...
```

写进配置：`./scripts/setup_key.sh <account> <key>`，或手动放进 `~/.wxre/config.json`。

### 3. 查

```bash
./bin/wxq ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_xxx/db_storage/message/message_0.db <KEY> \
  "select count(*) from sqlite_master where name like 'Msg_%'"
```

`wxq` 是**只读**的：`SQLITE_OPEN_READONLY` + 只允许 `select` 开头的语句，写操作直接返回 `readonly: only SELECT is allowed`。建议永远在 `cp -c` 克隆上跑，别碰正在写的原库。

### 4. 导出 / 页面

```bash
python3 scripts/export.py            # 全部库 → out/<account>/
python3 scripts/build_export.py      # → export/wechat.db（messages/chats/contacts/moments 四表）
python3 scripts/gen_html.py          # → export/index.html + chats/*.html
python3 scripts/chatquery.py --who 老婆 --days 3 --ask "最近在说什么"
```

DSH 插件页面见 [`dsh-plugin/`](dsh-plugin/)：左侧栏一页，会话/搜索/发送者筛选/AI 总结。

---

## 工具清单

| 文件 | 作用 |
|---|---|
| `tools/wxhook_dylib.c` | interpose `CCKeyDerivationPBKDF`，把 KDF 入参写日志（**抓钥核心**） |
| `tools/wxq.c` | 只读 SQLCipher 查询，输出 TSV，BLOB 走 `0x<hex>` |
| `tools/wxdec.c` | 库 → 明文库（`ATTACH … KEY ''` + `sqlcipher_export`） |
| `tools/wxsql.c` | 最小示例：`sqlite3_key(db, key, 32)` + prepare |
| `tools/scan_keys.c` | 老版本（4.0.x）用的内存扫 `x'<key><salt>'`，4.2 已失效，留作对照 |
| `tools/keytest.c` | 对任意内存区滑动窗口试 32 字节 key，用 page-1 HMAC 校验 |
| `tools/memgrep.c` / `probe.c` / `dumpregion.c` | 内存搜索 / 找 `x'` 模式 / dump 区间 |
| `tools/ptry.c` | 自签 + `ptrace(PT_ATTACH)` 的最小验证（SIP 关闭时不需要 root） |
| `scripts/export.py` | 批量解密 `db_storage` |
| `scripts/build_export.py` | 汇总成单文件 `wechat.db` |
| `scripts/chatquery.py` | 按人 / 时间 / 发送者查记录，可选 AI 总结 |
| `scripts/persona_build.py` | 从聊天记录算说话风格统计（语言画像） |
| `scripts/gen_html.py` / `gen_moments.py` / `serve.py` | 静态页面与本地搜索服务 |
| `dsh-plugin/` | DeepSeek Harness 插件：`server.mjs` + `client.js` 一页浏览 |

---

## 数据结构速览

详细版在 [`docs/REVERSE_ENGINEERING.md`](docs/REVERSE_ENGINEERING.md)。

- `message/message_0.db`：消息主体。每个会话一张 `Msg_<md5(username)>` 表，`Name2Id(rowid ↔ user_name)` 映射发送者。
- `message_content` 列：`WCDB_CT_message_content = 4` 时是 **zstd**（magic `28 B5 2F FD`），`0` 是明文。消息体形如 `<sender_wxid>:\n<body>`，body 多为 XML（appmsg/img/voicemsg/emoji/location）。
- `local_type`：1 文本、3 图片、34 语音、43 视频、47 表情、48 位置、50 通话、10000 系统。应用消息是高位变体，判据是 `(local_type & 0xFFFFFFFF) == 49`。
- `session/session.db` 的 `SessionTable` 给会话列表与摘要；`contact/contact.db` 给备注/昵称；`sns/sns.db` 的朋友圈在 `SnsTimeLine`。

---

## 常见坑

**`file is not a database (26)`** —— 密钥或用法不对。微信用的是 `sqlite3_key(db, <32 字节二进制>, 32)`，不是 `PRAGMA key="x'<64hex>'"`（raw key 语义），也不是 `PRAGMA key='<64hex 文本>'`（文本口令语义）。CLI 表达不了二进制口令，必须用 `wxq` 这种 C 层调用。

**每个账号一把 key** —— 小号 key 解不开大号库，否则一样是 rc=26。

**只用过河拆桥的一条** —— 解密/查询请在 `cp -c` 克隆上做（APFS 克隆，秒级、不占空间、不锁原库）。仓库里的 `wxq` 是只读的，但把只读工具指向正在写的库仍然不好。

**微信把库"工厂化"** —— 遇见过一次：微信把 `message_0.db` 挪到 `message_0.db.factory/<时间戳>/`，并用**新 salt 重新加密**（`rekey`），再建一个空库。那份档案用原 key 打不开。教训写在 [`docs/RECOVERY.md`](docs/RECOVERY.md)：**出事第一件事是别让微信继续写，把 `.factory` 目录和你的 `cp -c` 克隆都拷出来**。

---

## 参考与致谢

- [`ydotdog/wechat-export-macos`](https://github.com/ydotdog/wechat-export-macos)：4.0.x 的 `x'<key><salt>'` 扫描方法与 SQLCipher 参数，是本项目的起点（4.2 上该方法失效）。
- SQLCipher 4 的 page 格式与 HMAC 计算方式。
- 微信 4.2 的 UI 栈是 Qt（`QNSWindow`/`QNSView`），不是 AppKit —— 这决定了发送侧所有注入路线都走不通。

## License

MIT，见 [LICENSE](LICENSE)。仅供个人备份自己的数据使用。
