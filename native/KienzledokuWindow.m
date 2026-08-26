#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface KienzledokuWindowDelegate : NSObject
<NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate>
@property(nonatomic, strong) NSURL *startURL;
@property(nonatomic, strong) NSString *iconPath;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@end

@implementation KienzledokuWindowDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    NSScreen *screen = [NSScreen mainScreen];
    NSRect visible = screen != nil
        ? screen.visibleFrame
        : NSMakeRect(0, 0, 1280, 800);
    CGFloat width = MIN(1440.0, floor(visible.size.width * 0.94));
    CGFloat height = MIN(960.0, floor(visible.size.height * 0.94));
    NSRect frame = NSMakeRect(
        NSMidX(visible) - width / 2.0,
        NSMidY(visible) - height / 2.0,
        width,
        height);
    NSWindowStyleMask style =
        NSWindowStyleMaskTitled |
        NSWindowStyleMaskClosable |
        NSWindowStyleMaskMiniaturizable |
        NSWindowStyleMaskResizable;

    self.window = [[NSWindow alloc]
        initWithContentRect:frame
        styleMask:style
        backing:NSBackingStoreBuffered
        defer:NO];
    self.window.title = @"Kienzledoku 1.2.1";
    self.window.minSize = NSMakeSize(
        MIN(980.0, visible.size.width),
        MIN(700.0, visible.size.height));
    self.window.delegate = self;
    self.window.releasedWhenClosed = NO;

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];

    self.webView = [[WKWebView alloc]
        initWithFrame:self.window.contentView.bounds
        configuration:configuration];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.navigationDelegate = self;
    self.webView.UIDelegate = self;
    self.webView.customUserAgent = @"Kienzledoku-NativeWindow/1.2.1";
    [self.window.contentView addSubview:self.webView];

    if (self.iconPath.length > 0) {
        NSImage *icon = [[NSImage alloc] initWithContentsOfFile:self.iconPath];
        if (icon != nil) {
            NSApp.applicationIconImage = icon;
        }
    }

    [self.webView loadRequest:[NSURLRequest requestWithURL:self.startURL]];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)windowWillClose:(NSNotification *)notification {
    (void)notification;
    [NSApp terminate:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    (void)sender;
    return YES;
}

- (void)webViewDidClose:(WKWebView *)webView {
    (void)webView;
    [self.window close];
}

- (void)webView:(WKWebView *)webView
    decidePolicyForNavigationAction:(WKNavigationAction *)navigationAction
    decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    (void)webView;
    NSURL *url = navigationAction.request.URL;
    BOOL localHTTP =
        [url.scheme.lowercaseString isEqualToString:@"http"] &&
        [url.host isEqualToString:@"127.0.0.1"] &&
        url.port != nil;
    BOOL harmlessInternal = [url.scheme.lowercaseString isEqualToString:@"about"];
    BOOL productWebsite =
        [url.scheme.lowercaseString isEqualToString:@"https"] &&
        ([url.host.lowercaseString isEqualToString:@"kienzledoku.de"] ||
         [url.host.lowercaseString isEqualToString:@"www.kienzledoku.de"]);
    if (productWebsite) {
        [[NSWorkspace sharedWorkspace] openURL:url];
        decisionHandler(WKNavigationActionPolicyCancel);
        return;
    }
    decisionHandler((localHTTP || harmlessInternal)
        ? WKNavigationActionPolicyAllow
        : WKNavigationActionPolicyCancel);
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2 || argc > 3) {
            fprintf(stderr, "usage: kienzledoku_window http://127.0.0.1:PORT/ [icon.icns]\n");
            return 2;
        }

        NSString *rawURL = [NSString stringWithUTF8String:argv[1]];
        NSURL *url = [NSURL URLWithString:rawURL];
        BOOL valid =
            url != nil &&
            [url.scheme.lowercaseString isEqualToString:@"http"] &&
            [url.host isEqualToString:@"127.0.0.1"] &&
            url.port != nil;
        if (!valid) {
            fprintf(stderr, "Kienzledoku window accepts only loopback HTTP URLs\n");
            return 2;
        }

        NSApplication *application = [NSApplication sharedApplication];
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];

        KienzledokuWindowDelegate *delegate =
            [[KienzledokuWindowDelegate alloc] init];
        delegate.startURL = url;
        if (argc == 3) {
            delegate.iconPath = [NSString stringWithUTF8String:argv[2]];
        }
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
