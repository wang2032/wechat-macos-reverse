# 发送侧实验（都不可用，作为记录保留）

这里放的是「在微信里替人发消息」的两次尝试源码。**两条路都没打通**，代码只用来证明做过什么、卡在哪。

## A. 辅助功能（AX）+ 模拟按键 —— `wxagent.m`

思路：申请「辅助功能」权限，找到微信进程，`Cmd+F` 打开搜索、粘会话名、回车、粘正文、回车。

- 编译：`clang -O2 -fobjc-arc -framework Cocoa -framework ApplicationServices -o wxagent wxagent.m`
- 用法：`./wxagent check` 看授权；`./wxagent send --to "文件传输助手" "文本"`。
- 卡点：需要用户在「系统设置 → 隐私与安全性 → 辅助功能」里授权这个二进制；ad-hoc 签名每次重编都会让授权失效（TCC 按 cdhash 记）。且微信必须在最前台，否则按键进不去。

## B. 注入 dylib + 投递事件 —— `wxsend.m`

思路：把库注入微信进程，用 `[NSApp postEvent:]` / `CGEventPostToPid` 把按键投进它自己的事件队列，绕开系统级模拟，不需要 TCC 授权。

- 编译：`cc -O2 -dynamiclib -arch arm64e -o wxsend.dylib wxsend.m -framework Cocoa`（**必须 arm64e**）
- 卡点（详见 `docs/REVERSE_ENGINEERING.md`）：微信 4.2 的会话界面是 Qt（`QNSWindow` / `QNSView`）自绘的，五种投递方式全部返回成功，但消息没有进库 —— Qt 不处理合成事件。

## 结论

要在微信里真的发出去，只剩协议层（`sendmsg`=2 / `newsendmsg`=237 / `sendappmsg`=107），需要 protobuf 结构与登录态，且违反使用协议。本仓库不做这件事。

要自动提醒/日报，请用系统通知、企业微信群机器人这类正规通道（`src/wxr/notify.py` 里的 `macos` / `wecom` 通道就是干这个的）。
