// wxagent —— 通过辅助功能（AX）操作微信窗口发送消息。
// 只允许发给自己：白名单里的会话名（默认「文件传输助手」）。
//
//   wxagent send [--to NAME] [--dry] TEXT
//   wxagent check
//
// 首次运行会弹出「辅助功能」授权提示；授权后 osascript/本程序才能模拟键鼠。

#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

static const char *ALLOW[] = {"文件传输助手", "File Transfer", "文件传输", NULL};

static int allowed(const char *name) {
    for (int i = 0; ALLOW[i]; i++) if (strcmp(name, ALLOW[i]) == 0) return 1;
    return 0;
}

static void msleep(int ms) { usleep(ms * 1000); }

static void keycode(CGKeyCode code, CGEventFlags flags) {
    CGEventRef down = CGEventCreateKeyboardEvent(NULL, code, true);
    CGEventSetFlags(down, flags);
    CGEventPost(kCGHIDEventTap, down);
    msleep(12);
    CGEventRef up = CGEventCreateKeyboardEvent(NULL, code, false);
    CGEventSetFlags(up, flags);
    CGEventPost(kCGHIDEventTap, up);
    CFRelease(down);
    CFRelease(up);
    msleep(40);
}

// 用剪贴板粘贴：不受输入法影响，中文、换行都可靠
static void paste_text(NSString *s) {
    NSPasteboard *pb = [NSPasteboard generalPasteboard];
    [pb clearContents];
    [pb setString:s forType:NSPasteboardTypeString];
    msleep(60);
    keycode(0x09, kCGEventFlagMaskCommand);  // Cmd+V
}

static pid_t find_wechat(void) {
    for (NSRunningApplication *app in [[NSWorkspace sharedWorkspace] runningApplications]) {
        NSString *bid = app.bundleIdentifier ?: @"";
        NSString *name = app.localizedName ?: @"";
        if ([bid isEqualToString:@"com.tencent.xinWeChat"] || [name isEqualToString:@"WeChat"] ||
            [name isEqualToString:@"微信"]) {
            if (app.activationPolicy != NSApplicationActivationPolicyProhibited) return app.processIdentifier;
        }
    }
    return 0;
}

static const char *OUTPATH = NULL;

static int finish(int code, NSString *msg) {
    if (OUTPATH) {
        NSDictionary *d = @{@"code": @(code), @"msg": msg ?: @""};
        NSData *j = [NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
        [j writeToFile:@(OUTPATH) atomically:YES];
    }
    if (msg.length) {
        if (code) fprintf(stderr, "%s\n", msg.UTF8String);
        else printf("%s\n", msg.UTF8String);
    }
    return code;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        NSDictionary *opt = @{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES};
        BOOL trusted = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)opt);

        // --out 可以在任何位置：给「由 open 启动、没有 stdout」的场景用
        for (int i = 1; i < argc; i++) {
            if (strcmp(argv[i], "--out") == 0 && i + 1 < argc) OUTPATH = argv[++i];
        }

        const char *cmd = argc > 1 ? argv[1] : "check";
        if (strcmp(cmd, "check") == 0) {
            NSString *m = [NSString stringWithFormat:@"ax_trusted=%d\nwechat_pid=%d",
                           trusted ? 1 : 0, (int)find_wechat()];
            return finish(trusted ? 0 : 3, m);
        }

        const char *to = "文件传输助手";
        int dry = 0, any = 0;
        NSMutableString *body = [NSMutableString string];
        for (int i = 2; i < argc; i++) {
            if (strcmp(argv[i], "--to") == 0 && i + 1 < argc) { to = argv[++i]; }
            else if (strcmp(argv[i], "--dry") == 0) { dry = 1; }
            else if (strcmp(argv[i], "--any") == 0) { any = 1; }
            else if (strcmp(argv[i], "--out") == 0 && i + 1 < argc) { i++; }
            else { if (body.length) [body appendString:@" "]; [body appendString:@(argv[i])]; }
        }

        if (!trusted) {
            return finish(3, @"辅助功能未授权：系统设置 → 隐私与安全性 → 辅助功能，勾选 WxAgent.app");
        }
        pid_t pid = find_wechat();
        if (!pid) return finish(4, @"没找到运行中的微信");
        if (!any && !allowed(to)) return finish(5, [NSString stringWithFormat:@"拒绝：%s 不在白名单（发给自己才安全；确需发给他人加 --any）", to]);
        if (!dry && body.length == 0) return finish(2, @"消息为空");

        NSRunningApplication *app = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
        [app activateWithOptions:NSApplicationActivateAllWindows];
        msleep(500);

        keycode(0x03, kCGEventFlagMaskCommand);  // Cmd+F 搜索
        msleep(400);
        paste_text(@(to));                        // 搜索框里粘会话名
        msleep(800);
        keycode(0x24, 0);                         // Return 打开第一个结果
        msleep(900);

        if (dry) return finish(0, [NSString stringWithFormat:@"dry: 已打开 %s，未发送", to]);

        paste_text(body);
        msleep(350);
        keycode(0x24, 0);                         // Return 发送
        msleep(250);
        return finish(0, [NSString stringWithFormat:@"sent to %s: %@", to, body]);
    }
}
