// Real WebKit keyboard regression; synthetic values only. Clipboard restored.
#import <WebKit/WebKit.h>
#import "../native/KienzledokuMenus.h"

@interface EditTest : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *web;
@property(nonatomic, strong) NSArray<NSPasteboardItem *> *previousClipboard;
@property(nonatomic) NSInteger clipboardChange;
@property(nonatomic) BOOL password;
@end
@implementation EditTest
- (void)finish:(int)status {
    NSPasteboard *board = NSPasteboard.generalPasteboard;
    if (board.changeCount == self.clipboardChange) {
        [board clearContents];
        if (self.previousClipboard.count) [board writeObjects:self.previousClipboard];
    }
    if (status == 0) printf("Native Cmd-V into %s input OK\n", self.password ? "password" : "text");
    else fprintf(stderr,"Native keyboard paste failed\n");
    exit(status);
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSPasteboard *board = NSPasteboard.generalPasteboard;
    NSMutableArray *saved = [NSMutableArray array];
    for (NSPasteboardItem *item in board.pasteboardItems) {
        NSPasteboardItem *copy = [[NSPasteboardItem alloc] init];
        for (NSPasteboardType type in item.types) {
            NSData *data = [item dataForType:type];
            if (data) [copy setData:data forType:type];
        }
        [saved addObject:copy];
    }
    self.previousClipboard = saved;
    [board clearContents]; [board setString:@"synthetic-paste-Ä" forType:NSPasteboardTypeString];
    self.clipboardChange = board.changeCount;
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,500,200)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Synthetischer Tastaturtest";
    KienzledokuInstallMenus(self.window,@"Kienzledoku Tastaturtest");
    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    config.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];
    self.web = [[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:config];
    self.web.navigationDelegate = self;
    [self.window.contentView addSubview:self.web];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [self.window makeFirstResponder:self.web];
    [self.web loadHTMLString:[NSString stringWithFormat:@"<input id='value' type='%@'>", self.password ? @"password" : @"text"] baseURL:nil];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self finish:2];});
}
- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [webView evaluateJavaScript:@"document.getElementById('value').focus()" completionHandler:^(id value,NSError *error) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,200*NSEC_PER_MSEC),dispatch_get_main_queue(),^{
            NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                modifierFlags:NSEventModifierFlagCommand timestamp:0 windowNumber:self.window.windowNumber
                context:nil characters:@"v" charactersIgnoringModifiers:@"v" isARepeat:NO keyCode:9];
            if (![NSApp.mainMenu performKeyEquivalent:key]) { fprintf(stderr,"Shortcut not dispatched; active=%d keyWindow=%d\n", NSApp.active, self.window.keyWindow); [self finish:1]; return; }
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,200*NSEC_PER_MSEC),dispatch_get_main_queue(),^{
                [webView evaluateJavaScript:@"document.getElementById('value').value" completionHandler:^(id result,NSError *error) {
                    if (error || ![result isEqual:@"synthetic-paste-Ä"]) fprintf(stderr,"Paste dispatched but value not received; error=%d active=%d\n",error!=nil,NSApp.active);
                    [self finish:(!error && [result isEqual:@"synthetic-paste-Ä"]) ? 0 : 1];
                }];
            });
        });
    }];
}
@end
int main(int argc,const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        EditTest *test = [[EditTest alloc] init]; test.password = argc > 1;
        app.delegate = test; [app run];
    }
    return 0;
}
