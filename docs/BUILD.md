# 编译说明

环境：macOS（Apple Silicon），Xcode Command Line Tools，`brew install sqlcipher openssl@3`。

## wxq / wxdec / wxsql（C，SQLCipher）

静态链接（推荐，产物可单独分发，不依赖 brew 里的 dylib）：

```bash
mkdir -p bin
cc -O2 -o bin/wxq tools/wxq.c \
  "$(brew --prefix sqlcipher)/lib/libsqlcipher.a" \
  "$(brew --prefix openssl@3)/lib/libcrypto.a" \
  -framework Security -framework CoreFoundation -lz

# 校验：只剩系统框架依赖
otool -L bin/wxq
```

动态链接：

```bash
cc -O2 -I"$(brew --prefix sqlcipher)/include" -o wxq tools/wxq.c \
   -L"$(brew --prefix sqlcipher)/lib" -lsqlcipher
```

注意：`sqlite3_key()` 不在公开头文件里，源码顶部手写了声明：

```c
int sqlite3_key(sqlite3 *db, const void *pKey, int nKey);
```

## wxhook.dylib（注入库，抓密钥）

```bash
cc -O2 -dynamiclib -arch arm64e -o wxhook.dylib tools/wxhook_dylib.c -framework CoreFoundation
codesign -f -s - wxhook.dylib
```

`-arch arm64e` 是必须的：微信主程序是 arm64e，arm64 的 dylib 会被 dyld 拒绝
（`terminating because inserted dylib ... (have 'arm64', need 'arm64e')`）。

## 改签一份微信

```bash
cp -cR /Applications/WeChat.app ./WeChatHook.app
codesign -f -s - --entitlements docs/entitlements.wx.plist WeChatHook.app/Contents/MacOS/WeChat
codesign -dv --entitlements :- WeChatHook.app/Contents/MacOS/WeChat   # 应显示 flags=0x2(adhoc)
```

`entitlements.wx.plist` 需要包含微信原有的全部 entitlements（app-sandbox、application-groups、
network、temporary-exception 等，用 `codesign -d --entitlements :- /Applications/WeChat.app`
导出后改），再**追加**：

- `com.apple.security.cs.disable-library-validation` = true
- `com.apple.security.cs.allow-dyld-environment-variables` = true

重签时不要加 `--options runtime`，否则 hardened runtime 会挡 DYLD 注入。

## 其他小工具

```bash
cc -O2 -o memgrep tools/memgrep.c      && codesign -f -s - --entitlements docs/entitlements.devtool.plist memgrep
cc -O2 -o keytest tools/keytest.c      -lsqlcipher
cc -O2 -o scan_keys tools/scan_keys.c  && codesign -f -s - --entitlements docs/entitlements.devtool.plist scan_keys
cc -O2 -o ptry tools/ptry.c            && codesign -f -s - --entitlements docs/entitlements.devtool.plist ptry
```

`entitlements.devtool.plist` 只要两个键：

```xml
<key>com.apple.security.cs.debugger</key><true/>
<key>com.apple.security.get-task-allow</key><true/>
```

（SIP 关闭时，自签 + 这两个 entitlement 就能 `task_for_pid` / `ptrace(PT_ATTACH)`，
不需要 root。SIP 开启时这条不成立。）

## Python 侧

```bash
python3 -m pip install --user zstandard     # 可选；脚本里有 ctypes 直连 libzstd 的兜底
```

`wxr ask --ask` 需要一个大模型 API（默认 DeepSeek：`DEEPSEEK_API_KEY`），
不配也能用，只是没有 AI 总结。
