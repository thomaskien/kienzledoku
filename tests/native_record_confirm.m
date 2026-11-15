// Native regression: the real WKUIDelegate must resolve both confirm choices.
// No patient data, FHIR calls, microphone access or persistent WebKit storage.
#define main record_window_main
#include "../native/KienzledokuWindow.m"
#undef main

@interface ConfirmTest : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) KienzledokuWindowDelegate *record;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic) BOOL accept;
@property(nonatomic) BOOL clicked;
@end
@implementation ConfirmTest
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.record = [[KienzledokuWindowDelegate alloc] init];
    self.record.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,500,300)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    self.record.window.title = @"Synthetischer Dialogtest";
    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    config.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];
    self.record.webView = [[WKWebView alloc] initWithFrame:self.record.window.contentView.bounds configuration:config];
    self.record.webView.UIDelegate = self.record;
    self.record.webView.navigationDelegate = self;
    [self.record.window.contentView addSubview:self.record.webView];
    [self.record.window orderFront:nil];
    [self.record.webView loadHTMLString:@"<html><body>Synthetischer Dialogtest</body></html>" baseURL:nil];
    self.timer = [NSTimer scheduledTimerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *timer) {
        NSWindow *sheet = self.record.window.attachedSheet;
        if (sheet && !self.clicked) {
            NSString *title = self.accept ? @"Verwerfen und schließen" : @"Abbrechen";
            NSMutableArray<NSView *> *views = [NSMutableArray arrayWithObject:sheet.contentView];
            while (views.count) {
                NSView *view = views.lastObject; [views removeLastObject];
                if ([view isKindOfClass:NSButton.class] && [((NSButton *)view).title isEqualToString:title]) {
                    self.clicked = YES; [(NSButton *)view performClick:nil]; break;
                }
                [views addObjectsFromArray:view.subviews];
            }
        }
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10*NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        fprintf(stderr,"Native confirmation timed out\n"); exit(2);
    });
}
- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [webView evaluateJavaScript:@"confirm('Synthetische Aufnahme verwerfen?')" completionHandler:^(id result, NSError *error) {
        if (error || !self.clicked || [result boolValue] != self.accept) {
            fprintf(stderr,"Native confirmation did not deliver the selected choice\n"); exit(1);
        }
        printf("Native confirmation %s OK\n",self.accept ? "accept" : "cancel");
        [self.timer invalidate]; exit(0);
    }];
}
@end
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        ConfirmTest *test = [[ConfirmTest alloc] init];
        test.accept = argc > 1 && strcmp(argv[1],"accept") == 0;
        app.delegate = test; [app run];
    }
    return 0;
}
