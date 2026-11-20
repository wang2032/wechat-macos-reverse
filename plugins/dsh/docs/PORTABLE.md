# 把「微信记录」搬到别的 Mac

```
local-dsh-wx-browser-1.0.0.tgz   2.8MB
├── bin/wxq            静态链接 SQLCipher 的查询器（arm64，无依赖）
├── server.mjs         Node 服务（快照 + 解密查询 + HTTP，127.0.0.1:8778）
├── client.js          DSH 页面（会话列表 / 消息流 / 搜索 / 筛选 / 总结）
├── index.js           宿主半：插件加载时起服务
├── setup.mjs          换机初始化：写密钥 + 当场验证
└── docs/              这份说明
```

## 目标机需要什么

| 必需 | 说明 |
| --- | --- |
| Apple Silicon Mac | `bin/wxq` 是 arm64 静态二进制；Intel 需自己 `cc` 重编（见文末） |
| DSH | 插件要装进 DSH profile |
| 微信 4.2 且登录过大号 | 数据在 `~/Library/Containers/com.tencent.xinWeChat/.../xwechat_files/<账号>/db_storage` |
| 这把账号密钥 | **每台机、每个账号各不相同，必须自己搞到**（见下） |

不需要 Python、不需要 sqlcipher、不需要 brew、不需要改签微信。

## 三步装好

```bash
# 1) 装插件（把 tgz 放到任意路径）
dsh plugin install /path/to/local-dsh-wx-browser-1.0.0.tgz
#   或在 DSH 会话里让我调 plugin_manager install_bundle

# 2) 写账号+密钥，并当场验证（能列出会话数就说明密钥对）
node "$(dsh plugin path @local/dsh-wx-browser)/setup.mjs" \
     --account wxid_xxxxxxxxxxxx_xxxx --key <64位hex>

# 3) 刷新 DSH 页面（⌘R），左侧栏出现「微信记录」
```

服务由插件自己起（`127.0.0.1:8778`），不用另开进程。端口被占时：
`WX_BROWSER_PORT=8799`，页面里 `localStorage.wxBrowserApi='http://127.0.0.1:8799'`。

## 密钥怎么来

密钥是**账号级 32 字节**随机值，微信在登录时派生，运行时用
`sqlite3_key(db, key, 32)` 交给 SQLCipher。它不在磁盘上，只在内存里，所以必须抓一次。

两种抓法：

1. **从已经抓过的机器抄**（同一微信账号才可能通用）
   拿到 `~/.dsh-wx-browser/config.json` 里的 `key`，拷到新机器的同一路径，跑 `setup.mjs` 验证。
   同一账号在不同机器上是否同钥尚未确认——验证方式就是看 `setup.mjs` 能否列出会话。

2. **在新机器上抓**（不同账号必须走这条）
   用 `wechat-dump/` 那套工具：
   - `cp -cR /Applications/WeChat.app ~/WeChatHook.app`，用带
     `com.apple.security.cs.disable-library-validation` 与
     `com.apple.security.cs.allow-dyld-environment-variables` 的 entitlements 做 ad-hoc 重签；
   - `DYLD_INSERT_LIBRARIES=wxhook.dylib ~/WeChatHook.app/Contents/MacOS/WeChat` 启动，登录目标账号；
   - 日志里筛 `rounds=256000` 的 `pw`（每次 32 字节 / 16 字节 salt 一对），把候选 `pw` 逐个
     `bin/wxq <该机 session.db> <候选> "select count(*) from SessionTable"`，返回数字的那把就是；
   - 抓到后换回官方 `/Applications/WeChat.app`。

前提是这台机 SIP 已关（`csrutil status`）；没关就只能先关 SIP，或改用 `chatlog` 之类现成工具。

## 只读保证

`bin/wxq` 用 `sqlite3_open_v2(..., SQLITE_OPEN_READONLY)` 打开库，并在解析前拒绝任何非 `SELECT` 语句
（`readonly: only SELECT is allowed`，退出码 6）。查询跑在 `cp -c` 出来的 `/tmp` 克隆上，
原库连写权限都不申请。实测：连续 5 次查询前后，`session.db` 的 mtime 与 sha256 一字未变。

## 安全边界

- 服务只监听 `127.0.0.1`，没有鉴权——本机任何进程都能读，和微信本身同级别。
- 密钥默认存 `~/.dsh-wx-browser/config.json`（0600）；更稳妥用环境变量 `WX_KEY`，不落盘。
- 别把 tgz 和你的密钥一起发给别人：拿 paket + 密钥 = 拿你的聊天记录。

## 改与重发

```bash
cd dsh-wx-browser
node --check server.mjs && node --check client.js
npm version patch        # 或者手改 package.json
npm pack                 # 产出 local-dsh-wx-browser-<ver>.tgz
```

重编 `bin/wxq`（Intel 机器或想升级 SQLCipher）：

```bash
cc -O2 -o bin/wxq wxq.c \
   /opt/homebrew/opt/sqlcipher/lib/libsqlcipher.a \
   /opt/homebrew/opt/openssl@3/lib/libcrypto.a \
   -framework Security -framework CoreFoundation -lz
```

只要链上系统框架，产物就自带 SQLCipher，目标机什么依赖都不用装。
