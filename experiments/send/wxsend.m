// wxsend.dylib v5 —— 注入微信主进程，多通道尝试把按键送进它自己的 UI（不需要辅助功能授权）
//
// 命令文件：<容器 tmp>/wxsend.cmd      内容：PING | DUMP | 会话名<TAB>正文
// 模式文件：<容器 tmp>/wxsend.mode     内容：0..4（默认 0），用来挑选投递通道
// 结果文件：<容器 tmp>/wxsend.out
//
// 通道：
//   0 = [NSApp postEvent:] 到 keyWindow
//   1 = [NSApp postEvent:] 到 windowNumber 0
//   2 = CGEventPostToPid(getpid())
//   3 = [NSApp sendEvent:] 直接分发
//   4 = [窗口 sendEvent:] 直接投给可见主窗口
#import <Cocoa/Cocoa.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int g_mode = 0;

static NSString *TmpFile(NSString *n) { return [NSTemporaryDirectory() stringByAppendingPathComponent:n]; }
static void logln(NSString *s) { fprintf(stderr, "== wxsend: %s\n", s.UTF8String); }
static void writeOut(NSString *s) {
    [s writeToFile:TmpFile(@"wxsend.out") atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}

static NSWindow *mainVisibleWindow(void) {
    for (NSWindow *w in [NSApp windows]) if (w.isVisible && w.frame.size.width > 300) return w;
    return [NSApp keyWindow];
}

static void setPasteboard(NSString *text) {
    NSPasteboard *pb = [NSPasteboard generalPasteboard];
    [pb clearContents];
    [pb setString:text forType:NSPasteboardTypeString];
}

static void postKey(CGKeyCode code, NSEventModifierFlags flags, NSString *chars) {
    NSWindow *w = mainVisibleWindow();
    NSInteger win = (g_mode == 1) ? 0 : (w ? w.windowNumber : 0);

    NSEvent *(^mk)(NSEventType) = ^NSEvent *(NSEventType t) {
        return [NSEvent keyEventWithType:t location:NSZeroPoint modifierFlags:flags
                               timestamp:[[NSProcessInfo processInfo] systemUptime]
                            windowNumber:win context:nil characters:chars
           charactersIgnoringModifiers:chars isARepeat:NO keyCode:code];
    };

    if (g_mode == 2) {
        CGEventRef e = CGEventCreateKeyboardEvent(NULL, code, true);
        if (flags & NSEventModifierFlagCommand) CGEventSetFlags(e, kCGEventFlagMaskCommand);
        CGEventPostToPid(getpid(), e);
        CFRelease(e);
        CGEventRef u = CGEventCreateKeyboardEvent(NULL, code, false);
        if (flags & NSEventModifierFlagCommand) CGEventSetFlags(u, kCGEventFlagMaskCommand);
        CGEventPostToPid(getpid(), u);
        CFRelease(u);
        return;
    }
    NSEvent *down = mk(NSEventTypeKeyDown);
    NSEvent *up = mk(NSEventTypeKeyUp);
    if (g_mode == 3) {
        [NSApp sendEvent:down];
        [NSApp sendEvent:up];
    } else if (g_mode == 4 && w) {
        [w sendEvent:down];
        [w sendEvent:up];
    } else {
        [NSApp postEvent:down atStart:NO];
        [NSApp postEvent:up atStart:NO];
    }
}

static void bringUp(void) {
    if ([NSApp activationPolicy] != NSApplicationActivationPolicyRegular) {
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    }
    [NSApp unhide:nil];
    NSWindow *w = mainVisibleWindow();
    if (w) { [w makeKeyAndOrderFront:nil]; }
    [NSApp activateIgnoringOtherApps:YES];
}

static NSString *doSend(NSString *to, NSString *body) {
    bringUp();
    usleep(600 * 1000);

    setPasteboard(to);
    usleep(200 * 1000);
    postKey(0x03, NSEventModifierFlagCommand, @"f");
    usleep(700 * 1000);
    postKey(0x09, NSEventModifierFlagCommand, @"v");
    usleep(900 * 1000);
    postKey(0x24, 0, @"\r");
    usleep(1100 * 1000);
    setPasteboard(body);
    usleep(200 * 1000);
    postKey(0x09, NSEventModifierFlagCommand, @"v");
    usleep(400 * 1000);
    postKey(0x24, 0, @"\r");
    usleep(400 * 1000);
    return [NSString stringWithFormat:@"ok to=%@ chars=%lu mode=%d", to, (unsigned long)body.length, g_mode];
}

static NSString *doSnap(void) {
    NSWindow *w = mainVisibleWindow();
    if (!w) return @"err:no-window";
    [w displayIfNeeded];
    NSView *v = w.contentView;
    NSBitmapImageRep *rep = [v bitmapImageRepForCachingDisplayInRect:v.bounds];
    if (!rep) return @"err:no-rep";
    [v cacheDisplayInRect:v.bounds toBitmapImageRep:rep];
    NSData *png = [rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    [png writeToFile:TmpFile(@"wxsend.png") atomically:YES];
    return [NSString stringWithFormat:@"snap %ldx%ld bytes=%lu win=%ld %@",
            (long)rep.pixelsWide, (long)rep.pixelsHigh, (unsigned long)png.length,
            (long)w.windowNumber, NSStringFromClass([w class])];
}

static NSString *doDump(void) {
    NSMutableString *s = [NSMutableString string];
    NSResponder *fr = [[NSApp keyWindow] firstResponder];
    [s appendFormat:@"active=%d keywin=%ld policy=%ld hidden=%d firstResponder=%@\n",
        (int)[NSApp isActive], (long)[[NSApp keyWindow] windowNumber],
        (long)[NSApp activationPolicy], (int)[NSApp isHidden],
        fr ? NSStringFromClass([fr class]) : @"-"];
    for (NSWindow *w in [NSApp windows]) {
        [s appendFormat:@"win %ld %@ visible=%d key=%d main=%d frame=%.0fx%.0f title=%@\n",
            (long)w.windowNumber, NSStringFromClass([w class]), (int)w.isVisible,
            (int)w.isKeyWindow, (int)w.isMainWindow, w.frame.size.width, w.frame.size.height,
            w.title ?: @"-"];
    }
    return s;
}

static void pump(void) {
    NSString *cmdPath = TmpFile(@"wxsend.cmd");
    if (![[NSFileManager defaultManager] fileExistsAtPath:cmdPath]) return;
    NSString *req = [NSString stringWithContentsOfFile:cmdPath encoding:NSUTF8StringEncoding error:NULL];
    [[NSFileManager defaultManager] removeItemAtPath:cmdPath error:NULL];
    NSString *modeStr = [NSString stringWithContentsOfFile:TmpFile(@"wxsend.mode") encoding:NSUTF8StringEncoding error:NULL];
    if (modeStr.length) g_mode = modeStr.intValue;
    if (!req.length) { writeOut(@"err:empty"); return; }

    if ([req hasPrefix:@"PING"]) {
        writeOut([NSString stringWithFormat:@"pong active=%d windows=%lu keywin=%ld mode=%d",
                  (int)[NSApp isActive], (unsigned long)[[NSApp windows] count],
                  (long)[[NSApp keyWindow] windowNumber], g_mode]);
        return;
    }
    if ([req hasPrefix:@"KEY "]) {
        // KEY <keycode> <flags>  —— 手动投一个键，配合 DUMP 观察反应
        NSArray<NSString *> *p = [req componentsSeparatedByString:@" "];
        CGKeyCode kc = (CGKeyCode)(p.count > 1 ? p[1].intValue : 0);
        NSEventModifierFlags fl = (NSEventModifierFlags)(p.count > 2 ? strtoul(p[2].UTF8String, NULL, 10) : 0);
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
            bringUp();
            postKey(kc, fl, kc == 0x03 ? @"f" : (kc == 0x09 ? @"v" : @"\r"));
            usleep(1200 * 1000);
            writeOut([NSString stringWithFormat:@"key %u flags=%lu\n%@", kc, (unsigned long)fl, doDump()]);
        });
        CFRunLoopWakeUp(CFRunLoopGetMain());
        return;
    }
    if ([req hasPrefix:@"SNAP"]) {
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
            NSString *r = doSnap();
            writeOut(r);
        });
        CFRunLoopWakeUp(CFRunLoopGetMain());
        return;
    }
    if ([req hasPrefix:@"UP"]) {
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
            bringUp();
            writeOut([NSString stringWithFormat:@"up active=%d policy=%ld hidden=%d",
                      (int)[NSApp isActive], (long)[NSApp activationPolicy], (int)[NSApp isHidden]]);
        });
        CFRunLoopWakeUp(CFRunLoopGetMain());
        return;
    }
    if ([req hasPrefix:@"DUMP"]) {
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{ writeOut(doDump()); });
        CFRunLoopWakeUp(CFRunLoopGetMain());
        return;
    }

    NSRange tab = [req rangeOfString:@"\t"];
    if (tab.location == NSNotFound) { writeOut(@"err:no-tab"); return; }
    NSString *to = [req substringToIndex:tab.location];
    NSString *body = [[req substringFromIndex:tab.location + 1]
                      stringByTrimmingCharactersInSet:[NSCharacterSet newlineCharacterSet]];
    if (!to.length || !body.length) { writeOut(@"err:empty-field"); return; }
    writeOut(@"pending");
    NSString *capTo = [to copy], *capBody = [body copy];
    CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
        writeOut(doSend(capTo, capBody));
        logln(@"sent");
    });
    CFRunLoopWakeUp(CFRunLoopGetMain());
}

static int is_main_process(void) {
    static int v = -1;
    if (v < 0) {
        NSString *exe = [[NSBundle mainBundle] executablePath] ?: @"";
        v = [exe hasSuffix:@"/Contents/MacOS/WeChat"] ? 1 : 0;
    }
    return v;
}

static void *poller(void *arg) {
    (void)arg;
    logln([NSString stringWithFormat:@"poller pid=%d", getpid()]);
    for (;;) { pump(); usleep(200 * 1000); }
    return NULL;
}

__attribute__((constructor)) static void init(void) {
    fprintf(stderr, "== wxsend v5: loaded pid=%d main=%d\n", getpid(), is_main_process());
    if (!is_main_process()) return;
    pthread_t th;
    if (pthread_create(&th, NULL, poller, NULL) == 0) pthread_detach(th);
}
