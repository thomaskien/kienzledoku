#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import "KienzledokuMenus.h"

static NSString *const KienzledokuInstallerVersion = @"1.8.2";

@interface KienzledokuInstallerDelegate : NSObject
    <NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSView *loadingView;
@property(nonatomic, strong) NSTextField *loadingLabel;
@property(nonatomic, strong) NSProgressIndicator *spinner;
@property(nonatomic, strong) NSTask *backendTask;
@property(nonatomic, strong) NSPipe *stdoutPipe;
@property(nonatomic, strong) NSPipe *stderrPipe;
@property(nonatomic, strong) NSMutableData *stdoutBuffer;
@property(nonatomic, strong) NSMutableData *stderrBuffer;
@property(nonatomic, strong) NSURL *backendURL;
@property(nonatomic) BOOL installationBusy;
@property(nonatomic) BOOL backendWasStoppedByApp;
@property(nonatomic) BOOL receivedBackendURL;
@end

@implementation KienzledokuInstallerDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    [self buildWindow];
    KienzledokuInstallMenus(self.window, @"kienzledoku Installation");
    [self startBackend];
}

- (void)buildWindow {
    NSScreen *screen = NSScreen.mainScreen;
    NSRect visible = screen != nil ? screen.visibleFrame : NSMakeRect(0, 0, 1280, 900);
    CGFloat width = MIN(1080.0, MAX(760.0, floor(visible.size.width * 0.94)));
    CGFloat height = MIN(820.0, MAX(640.0, floor(visible.size.height * 0.94)));
    NSRect frame = NSMakeRect(NSMidX(visible) - width / 2.0,
                              NSMidY(visible) - height / 2.0,
                              width, height);
    NSWindowStyleMask style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                              NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable;
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:style
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.title = [NSString stringWithFormat:@"kienzledoku installieren %@", KienzledokuInstallerVersion];
    self.window.minSize = NSMakeSize(MIN(760.0, visible.size.width), MIN(640.0, visible.size.height));
    self.window.delegate = self;
    self.window.releasedWhenClosed = NO;

    NSView *content = self.window.contentView;
    content.wantsLayer = YES;
    content.layer.backgroundColor = [NSColor colorWithRed:0.965 green:0.976 blue:0.988 alpha:1.0].CGColor;
    self.loadingView = [[NSView alloc] initWithFrame:content.bounds];
    self.loadingView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;

    self.spinner = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(0, 0, 36, 36)];
    self.spinner.style = NSProgressIndicatorStyleSpinning;
    self.spinner.controlSize = NSControlSizeRegular;
    self.spinner.displayedWhenStopped = YES;
    [self.spinner startAnimation:nil];

    self.loadingLabel = [NSTextField labelWithString:@"Installationsassistent wird gestartet …"];
    self.loadingLabel.alignment = NSTextAlignmentCenter;
    self.loadingLabel.font = [NSFont systemFontOfSize:16 weight:NSFontWeightSemibold];
    self.loadingLabel.textColor = NSColor.labelColor;
    self.loadingLabel.maximumNumberOfLines = 0;
    self.loadingLabel.preferredMaxLayoutWidth = 620;

    NSStackView *stack = [NSStackView stackViewWithViews:@[self.spinner, self.loadingLabel]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeCenterX;
    stack.spacing = 16;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.loadingView addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.centerXAnchor constraintEqualToAnchor:self.loadingView.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:self.loadingView.centerYAnchor]
    ]];
    [content addSubview:self.loadingView];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (void)startBackend {
    NSURL *resources = NSBundle.mainBundle.resourceURL;
    if (resources == nil) {
        [self showStartupError:@"Die Ressourcen der App konnten nicht gefunden werden."];
        return;
    }
    NSURL *payload = [resources URLByAppendingPathComponent:@"payload" isDirectory:YES];
    NSURL *wizard = [payload URLByAppendingPathComponent:@"installer/wizard.py"];
    NSURL *runtime = [resources URLByAppendingPathComponent:@"runtime/python" isDirectory:YES];
    NSArray<NSString *> *pythonNames = @[@"python3.12", @"python3"];
    NSURL *python = nil;
    NSFileManager *files = NSFileManager.defaultManager;
    for (NSString *name in pythonNames) {
        NSURL *candidate = [[runtime URLByAppendingPathComponent:@"bin" isDirectory:YES] URLByAppendingPathComponent:name];
        if ([files isExecutableFileAtPath:candidate.path]) { python = candidate; break; }
    }
    if (python == nil) {
        [self showStartupError:@"Die mitgelieferte Python-Laufzeit fehlt oder ist nicht ausführbar. Bitte laden Sie den Installer erneut herunter."];
        return;
    }
    if (![files isReadableFileAtPath:wizard.path]) {
        [self showStartupError:@"Das Installationsprogramm ist unvollständig. Bitte laden Sie den Installer erneut herunter."];
        return;
    }

    self.stdoutBuffer = [NSMutableData data];
    self.stderrBuffer = [NSMutableData data];
    self.stdoutPipe = [NSPipe pipe];
    self.stderrPipe = [NSPipe pipe];
    self.backendTask = [[NSTask alloc] init];
    self.backendTask.executableURL = python;
    self.backendTask.arguments = @[wizard.path, @"--serve", @"--stdio"];
    self.backendTask.currentDirectoryURL = payload;
    self.backendTask.standardInput = [NSPipe pipe];
    self.backendTask.standardOutput = self.stdoutPipe;
    self.backendTask.standardError = self.stderrPipe;

    NSMutableDictionary<NSString *, NSString *> *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    NSString *runtimeBin = [runtime URLByAppendingPathComponent:@"bin" isDirectory:YES].path;
    [environment removeObjectForKey:@"PYTHONHOME"];
    [environment removeObjectForKey:@"PYTHONPATH"];
    environment[@"PYTHONNOUSERSITE"] = @"1";
    environment[@"PYTHONDONTWRITEBYTECODE"] = @"1";
    environment[@"PATH"] = [NSString stringWithFormat:@"%@:/usr/bin:/bin", runtimeBin];
    [environment removeObjectForKey:@"DYLD_LIBRARY_PATH"];
    [environment removeObjectForKey:@"DYLD_FALLBACK_LIBRARY_PATH"];
    self.backendTask.environment = environment;

    __weak typeof(self) weakSelf = self;
    self.stdoutPipe.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (data.length == 0) return;
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf consumeStdout:data]; });
    };
    self.stderrPipe.fileHandleForReading.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = handle.availableData;
        if (data.length == 0) return;
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf consumeStderr:data]; });
    };
    self.backendTask.terminationHandler = ^(NSTask *task) {
        int status = task.terminationStatus;
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf backendEndedWithStatus:status]; });
    };

    NSError *error = nil;
    if (![self.backendTask launchAndReturnError:&error]) {
        self.stdoutPipe.fileHandleForReading.readabilityHandler = nil;
        self.stderrPipe.fileHandleForReading.readabilityHandler = nil;
        [self showStartupError:[NSString stringWithFormat:@"Der Installationsdienst konnte nicht gestartet werden. %@", error.localizedDescription ?: @""]];
    }
}

- (void)consumeStdout:(NSData *)data {
    if (self.receivedBackendURL) return;
    [self.stdoutBuffer appendData:data];
    const unsigned char *bytes = self.stdoutBuffer.bytes;
    NSUInteger length = self.stdoutBuffer.length;
    for (NSUInteger index = 0; index < length; index++) {
        if (bytes[index] != '\n') continue;
        NSData *lineData = [self.stdoutBuffer subdataWithRange:NSMakeRange(0, index)];
        NSString *line = [[NSString alloc] initWithData:lineData encoding:NSUTF8StringEncoding];
        line = [line stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        self.receivedBackendURL = YES;
        [self loadBackendURLString:line];
        [self.stdoutBuffer setLength:0];
        return;
    }
    if (length > 8192) {
        self.receivedBackendURL = YES;
        [self showStartupError:@"Der Installationsdienst hat keine gültige lokale Adresse geliefert."];
        [self stopBackend];
    }
}

- (void)consumeStderr:(NSData *)data {
    static const NSUInteger limit = 1000;
    if (self.stderrBuffer.length >= limit) return;
    NSUInteger remaining = limit - self.stderrBuffer.length;
    [self.stderrBuffer appendData:data.length <= remaining ? data : [data subdataWithRange:NSMakeRange(0, remaining)]];
}

- (void)loadBackendURLString:(NSString *)rawURL {
    NSURL *url = [NSURL URLWithString:rawURL ?: @""];
    BOOL valid = url != nil && [url.scheme.lowercaseString isEqualToString:@"http"] &&
                 [url.host isEqualToString:@"127.0.0.1"] && url.port != nil;
    if (!valid) {
        [self showStartupError:@"Der Installationsdienst hat keine gültige lokale Adresse geliefert."];
        [self stopBackend];
        return;
    }
    self.backendURL = url;
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    [configuration.userContentController addScriptMessageHandler:self name:@"installer"];
    self.webView = [[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:configuration];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.navigationDelegate = self;
    self.webView.customUserAgent = [NSString stringWithFormat:@"kienzledoku-installer/%@", KienzledokuInstallerVersion];
    [self.window.contentView addSubview:self.webView positioned:NSWindowAbove relativeTo:self.loadingView];
    [self.webView loadRequest:[NSURLRequest requestWithURL:url]];
}

- (void)showStartupError:(NSString *)message {
    [self.spinner stopAnimation:nil];
    self.spinner.hidden = YES;
    self.loadingLabel.textColor = NSColor.systemRedColor;
    self.loadingLabel.stringValue = message.length > 0 ? message : @"Der Installationsassistent wurde unerwartet beendet.";
    [self.loadingView.superview addSubview:self.loadingView positioned:NSWindowAbove relativeTo:nil];
}

- (void)backendEndedWithStatus:(int)status {
    self.stdoutPipe.fileHandleForReading.readabilityHandler = nil;
    self.stderrPipe.fileHandleForReading.readabilityHandler = nil;
    if (self.backendWasStoppedByApp) return;
    NSString *technical = [[NSString alloc] initWithData:self.stderrBuffer encoding:NSUTF8StringEncoding];
    technical = [technical stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *message = [NSString stringWithFormat:@"Der Installationsdienst wurde unerwartet beendet (Status %d).", status];
    if (technical.length > 0) message = [message stringByAppendingFormat:@"\n\nTechnischer Hinweis:\n%@", technical];
    [self showStartupError:message];
}

- (void)stopBackend {
    if (self.backendTask != nil && self.backendTask.running) {
        self.backendWasStoppedByApp = YES;
        [self.backendTask terminate];
    }
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender;
    if (!self.installationBusy) return YES;
    NSAlert *alert = [[NSAlert alloc] init];
    alert.alertStyle = NSAlertStyleWarning;
    alert.messageText = @"Laufende Installation abbrechen?";
    alert.informativeText = @"Beim Schließen wird nur der Installationsdienst dieser App beendet. Bereits angelegte Sicherungen bleiben erhalten.";
    [alert addButtonWithTitle:@"Nicht schließen"];
    [alert addButtonWithTitle:@"Installation abbrechen"];
    return [alert runModal] == NSAlertSecondButtonReturn;
}

- (void)windowWillClose:(NSNotification *)notification {
    (void)notification;
    [self stopBackend];
    [NSApp terminate:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    (void)sender;
    return YES;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    [self stopBackend];
    return NSTerminateNow;
}

- (void)userContentController:(WKUserContentController *)userContentController
      didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)userContentController;
    if (![message.name isEqualToString:@"installer"] || ![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *body = (NSDictionary *)message.body;
    NSString *action = [body[@"action"] isKindOfClass:NSString.class] ? body[@"action"] : @"";
    if ([action isEqualToString:@"copy"] && [body[@"text"] isKindOfClass:NSString.class]) {
        NSPasteboard *pasteboard = NSPasteboard.generalPasteboard;
        [pasteboard clearContents];
        [pasteboard setString:body[@"text"] forType:NSPasteboardTypeString];
    } else if ([action isEqualToString:@"close"] && !self.installationBusy) {
        [self.window performClose:nil];
    } else if ([action isEqualToString:@"busy"] && [body[@"value"] respondsToSelector:@selector(boolValue)]) {
        self.installationBusy = [body[@"value"] boolValue];
    }
}

- (BOOL)isApprovedExternalURL:(NSURL *)url {
    if (![url.scheme.lowercaseString isEqualToString:@"https"]) return NO;
    NSString *host = url.host.lowercaseString ?: @"";
    NSArray<NSString *> *domains = @[@"github.com", @"kienzledoku.de", @"huggingface.co"];
    for (NSString *domain in domains) {
        if ([host isEqualToString:domain] || [host hasSuffix:[@"." stringByAppendingString:domain]]) return YES;
    }
    return NO;
}

- (void)webView:(WKWebView *)webView
    decidePolicyForNavigationAction:(WKNavigationAction *)navigationAction
    decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    (void)webView;
    NSURL *url = navigationAction.request.URL;
    BOOL local = [url.scheme.lowercaseString isEqualToString:@"http"] &&
                 [url.host isEqualToString:@"127.0.0.1"] &&
                 [url.port isEqual:self.backendURL.port];
    BOOL internal = [url.scheme.lowercaseString isEqualToString:@"about"];
    if ([self isApprovedExternalURL:url]) {
        [NSWorkspace.sharedWorkspace openURL:url];
        decisionHandler(WKNavigationActionPolicyCancel);
        return;
    }
    decisionHandler((local || internal) ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}

@end

int main(int argc, const char *argv[]) {
    (void)argc; (void)argv;
    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        application.activationPolicy = NSApplicationActivationPolicyRegular;
        KienzledokuInstallerDelegate *delegate = [[KienzledokuInstallerDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
