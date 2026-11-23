#import <Cocoa/Cocoa.h>
#import <fcntl.h>
#import <sys/file.h>
#import <sys/stat.h>

#if defined(__arm64__)
#define KD_ARCH "arm64"
#else
#define KD_ARCH "x86_64"
#endif
#import <unistd.h>

static void Notice(NSString *title, NSString *detail) {
    NSAlert *alert = [NSAlert new];
    alert.messageText = title;
    alert.informativeText = detail;
    [NSApp activateIgnoringOtherApps:YES];
    [alert runModal];
}

static NSURL *ConfigDirectory(void) {
    NSString *override = NSProcessInfo.processInfo.environment[@"KIENZLEDOKU_CONFIG_DIR"];
    if (override.length) return [NSURL fileURLWithPath:override isDirectory:YES];
    return [[NSFileManager.defaultManager URLsForDirectory:NSApplicationSupportDirectory
                                                 inDomains:NSUserDomainMask].firstObject
            URLByAppendingPathComponent:@"Kienzledoku" isDirectory:YES];
}

static BOOL HasConfiguration(void) {
    return [NSFileManager.defaultManager fileExistsAtPath:
            [ConfigDirectory() URLByAppendingPathComponent:@"config.toml"].path];
}

static NSArray<NSString *> *Schemes(void) {
    return @[@"kienzledoku-record", @"kienzledoku"];
}

static BOOL AcceptsURL(NSURL *url) {
    NSURLComponents *parts = [NSURLComponents componentsWithURL:url resolvingAgainstBaseURL:NO];
    return [Schemes() containsObject:parts.scheme.lowercaseString]
        && [parts.host.lowercaseString isEqualToString:@"record"]
        && !parts.user && !parts.password && !parts.port && !parts.fragment
        && (!parts.percentEncodedPath.length || [parts.percentEncodedPath isEqualToString:@"/"])
        && [url.absoluteString lengthOfBytesUsingEncoding:NSUTF8StringEncoding] <= 65536;
}

@interface KDClient : NSObject <NSApplicationDelegate>
@property (strong) NSURL *python;
@property (strong) NSMutableArray<NSURL *> *links;
@property (strong) NSMutableSet<NSTask *> *children;
@property (strong) NSFileHandle *log;
@property BOOL logAttempted;
@property BOOL deferPatient;
@property BOOL configuring;
@property BOOL removing;
@property BOOL started;
@property BOOL requestedSettings;
@property BOOL receivedURL;
@end

@implementation KDClient
- (instancetype)init {
    self = [super init];
    if (self) { _links = [NSMutableArray new]; _children = [NSMutableSet new]; }
    return self;
}

// Only static stage names, system/version information and exit status, never links or task output.
- (void)logStage:(NSString *)message {
    if (!self.log) return;
    NSString *line = [NSString stringWithFormat:@"%@ [Client] %@\n", NSDate.date, message];
    [self.log writeData:[line dataUsingEncoding:NSUTF8StringEncoding] error:NULL];
}
- (void)startLog {
    if (self.logAttempted) return;
    self.logAttempted = YES;
    NSURL *desktop = [NSFileManager.defaultManager URLsForDirectory:NSDesktopDirectory inDomains:NSUserDomainMask].firstObject;
    NSString *name = [NSString stringWithFormat:@"KienzleDoku-1.8.3-Einrichtung-%@.log", NSUUID.UUID.UUIDString];
    NSURL *url = [desktop URLByAppendingPathComponent:name];
    if (!url) return;
    int fd = open(url.fileSystemRepresentation, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0600);
    if (fd < 0) return;
    self.log = [[NSFileHandle alloc] initWithFileDescriptor:fd closeOnDealloc:YES];
    [self logStage:[@"Einzelapp " KD_ARCH ", macOS " stringByAppendingString:NSProcessInfo.processInfo.operatingSystemVersionString]];
}
- (NSString *)probe:(NSURL *)candidate {
    if (![NSFileManager.defaultManager isExecutableFileAtPath:candidate.path]) return nil;
    NSTask *task = [NSTask new];
    task.executableURL = candidate;
    task.environment = @{@"PATH":@"/usr/bin:/bin"};
    NSString *check = @"import platform, ssl, sys\n"
        "if sys.implementation.name != 'cpython' or sys.version_info[:2] != (3,12) or platform.machine() != '" KD_ARCH "' or sys.prefix != sys.base_prefix: sys.exit(1)\n"
        "print(platform.python_version())";
    task.arguments = @[@"-I", @"-B", @"-c", check];
    NSPipe *pipe = [NSPipe pipe];
    task.standardOutput = pipe;
    task.standardError = NSFileHandle.fileHandleWithNullDevice;
    task.standardInput = NSFileHandle.fileHandleWithNullDevice;
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    task.terminationHandler = ^(NSTask *finished) { dispatch_semaphore_signal(done); };
    if (![task launchAndReturnError:NULL]) return nil;
    if (dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,15*NSEC_PER_SEC))) {
        if (task.running) [task terminate];
        return nil;
    }
    if (task.terminationStatus != 0) return nil;
    NSString *version = [[NSString alloc] initWithData:pipe.fileHandleForReading.readDataToEndOfFile
                                              encoding:NSUTF8StringEncoding];
    version = [version stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (![version hasPrefix:@"3.12."] || version.length > 16 ||
        [version rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"0123456789."].invertedSet].location != NSNotFound) return nil;
    return version;
}
- (void)findPython:(NSArray<NSString *> *)paths {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
        for (NSString *path in paths) {
            NSURL *candidate = [NSURL fileURLWithPath:path];
            NSString *version = [self probe:candidate];
            if (!version) continue;
            dispatch_async(dispatch_get_main_queue(), ^{
                self.python = candidate;
                [self logStage:[@"Externes CPython " KD_ARCH " gefunden: " stringByAppendingString:version]];
                [self dispatchRequests];
            });
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [self choosePython]; });
    });
}
- (void)choosePython {
    [self startLog];
    [self logStage:@"Kein passendes externes Python gefunden."];
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"Python 3.12 für Ihren Mac erforderlich";
    alert.informativeText = @"Installieren Sie CPython 3.12 (Intel oder Apple Silicon passend zu Ihrem Mac). Die Anleitung in der DMG enthält den Link zum grafischen Python.org-Installer (3.12.10, ohne spätere Sicherheitskorrekturen). Mit Homebrew erhalten Sie eine gepflegte 3.12-Version über brew install python@3.12. Bei einer eigenen Installation wählen Sie python3.12.";
    [alert addButtonWithTitle:@"Beenden"];
    [alert addButtonWithTitle:@"Python auswählen …"];
    [alert addButtonWithTitle:@"Python.org öffnen"];
    [NSApp activateIgnoringOtherApps:YES];
    NSModalResponse choice = [alert runModal];
    if (choice == NSAlertThirdButtonReturn) {
        [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:@"https://www.python.org/downloads/release/python-31210/"]];
    }
    if (choice == NSAlertSecondButtonReturn) {
        NSOpenPanel *picker = NSOpenPanel.openPanel;
        picker.canChooseDirectories = NO;
        picker.showsHiddenFiles = YES;
        if ([picker runModal] == NSModalResponseOK) {
            // Persist a path only after the compatibility probe accepts the file.
            NSString *path = picker.URL.path;
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
                NSString *version = [self probe:[NSURL fileURLWithPath:path]];
                dispatch_async(dispatch_get_main_queue(), ^{
                    if (!version) { [self choosePython]; return; }
                    [NSUserDefaults.standardUserDefaults setObject:path forKey:@"ExternalCPython312"];
                    self.python = [NSURL fileURLWithPath:path];
                    [self logStage:[@"Manuell gewähltes CPython: " stringByAppendingString:version]];
                    [self dispatchRequests];
                });
            });
            return;
        }
    }
    [NSApp terminate:nil];
}
- (void)assignSchemeAtIndex:(NSUInteger)index completion:(void (^)(void))completion {
    if (index == Schemes().count) { completion(); return; }
    if (@available(macOS 12.0, *)) {
        [NSWorkspace.sharedWorkspace setDefaultApplicationAtURL:NSBundle.mainBundle.bundleURL
                                          toOpenURLsWithScheme:Schemes()[index] completionHandler:^(NSError *error) {
            dispatch_async(dispatch_get_main_queue(), ^{
                if (error) { Notice(@"Zuordnung nicht übernommen", Schemes()[index]); completion(); return; }
                [self assignSchemeAtIndex:index+1 completion:completion];
            });
        }];
    } else {
        Notice(@"Zuordnung", @"Diese Funktion benötigt macOS 12 oder neuer.");
        completion();
    }
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSNumber *readOnly = nil;
    [NSBundle.mainBundle.bundleURL getResourceValue:&readOnly forKey:NSURLVolumeIsReadOnlyKey error:NULL];
    if (readOnly.boolValue) {
        Notice(@"KienzleDoku zuerst kopieren", @"Ziehen Sie KienzleDoku.app aus dem Image nach Programme und öffnen Sie die kopierte App.");
        [NSApp terminate:nil]; return;
    }
    if (!HasConfiguration()) [self startLog];
    NSMutableOrderedSet *paths = [NSMutableOrderedSet orderedSet];
    NSString *saved = [NSUserDefaults.standardUserDefaults stringForKey:@"ExternalCPython312"];
    if (saved.isAbsolutePath) [paths addObject:saved];
    [paths addObjectsFromArray:@[@"/opt/homebrew/opt/python@3.12/bin/python3.12",
        @"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
        @"/opt/homebrew/bin/python3.12", @"/usr/local/opt/python@3.12/bin/python3.12", @"/opt/local/bin/python3.12", @"/usr/local/bin/python3.12"]];
    void (^begin)(void) = ^{
        self.started = YES;
        [self findPython:paths.array];
        // Launch Services may deliver the initial URL after didFinishLaunching.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 350*NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
            if (!self.receivedURL && !self.children.count) {
                self.requestedSettings = YES;
                [self dispatchRequests];
            }
        });
    };
    if (NSEvent.modifierFlags & NSEventModifierFlagOption) {
        NSAlert *ask = [NSAlert new]; ask.messageText = @"T2med-Aufrufe mit dieser App öffnen?";
        ask.informativeText = @"Die Zuordnung gilt für Record und Connect. macOS kann dafür eine Bestätigung verlangen.";
        [ask addButtonWithTitle:@"Zuordnen"]; [ask addButtonWithTitle:@"Überspringen"];
        [NSApp activateIgnoringOtherApps:YES];
        if ([ask runModal] == NSAlertFirstButtonReturn) { [self assignSchemeAtIndex:0 completion:begin]; return; }
    }
    begin();
}
- (void)application:(NSApplication *)app openURLs:(NSArray<NSURL *> *)urls {
    if (self.removing) return;
    self.receivedURL = YES;
    for (NSURL *url in urls) {
        if (!AcceptsURL(url)) { Notice(@"Ungültiger T2med-Aufruf", @"Erwartet wird ein Record- oder Connect-Aufruf für record."); continue; }
        if (self.configuring) { self.deferPatient = YES; continue; }
        [self.links addObject:url];
    }
    if (self.links.count) self.requestedSettings = NO;
    [self dispatchRequests];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
    if (self.started && !self.children.count && !self.configuring) {
        self.requestedSettings = YES;
        [self dispatchRequests];
    }
    return NO;
}
- (void)dispatchRequests {
    if (!self.started || !self.python || self.configuring || self.removing) return;
    if (!self.links.count && !self.requestedSettings) return;
    if (!HasConfiguration()) {
        self.deferPatient |= self.links.count > 0;
        [self.links removeAllObjects]; self.requestedSettings = NO;
        self.configuring = YES;
        [self launchMode:@"--setup" link:nil];
        return;
    }
    NSArray *links = [self.links copy]; [self.links removeAllObjects];
    for (NSURL *url in links) [self launchMode:@"--deep-link-stdin" link:url];
    if (self.requestedSettings) {
        self.requestedSettings = NO;
        if (!self.children.count) [self launchMode:@"--settings" link:nil];
    }
}
- (void)launchMode:(NSString *)mode link:(NSURL *)url {
    NSURL *resources = NSBundle.mainBundle.resourceURL;
    NSTask *task = [NSTask new];
    task.executableURL = self.python;
    NSMutableArray *args = [@[@"-I", @"-B", [resources URLByAppendingPathComponent:@"client.py"].path] mutableCopy];
    if ([url.scheme.lowercaseString isEqualToString:@"kienzledoku"]) [args addObject:@"--from-connect"];
    [args addObject:mode]; task.arguments = args;
    task.currentDirectoryURL = resources;
    NSMutableDictionary *env = [NSProcessInfo.processInfo.environment mutableCopy];
    [env removeObjectsForKeys:@[@"PYTHONHOME",@"PYTHONPATH",@"DYLD_LIBRARY_PATH",@"DYLD_FALLBACK_LIBRARY_PATH"]];
    env[@"PYTHONDONTWRITEBYTECODE"] = @"1"; env[@"PYTHONNOUSERSITE"] = @"1";
    task.environment = env;
    NSPipe *input = url ? [NSPipe pipe] : nil;
    task.standardInput = input ? (id)input : NSFileHandle.fileHandleWithNullDevice;
    task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
    task.standardError = NSFileHandle.fileHandleWithNullDevice;
    BOOL setup = [mode isEqualToString:@"--setup"];
    [self logStage:[@"Start " stringByAppendingString:mode]];
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self.children removeObject:finished];
            [self logStage:[NSString stringWithFormat:@"%@ abgeschlossen, Status %d", mode, finished.terminationStatus]];
            if ([mode isEqualToString:@"--settings"] && finished.terminationReason == NSTaskTerminationReasonExit && finished.terminationStatus == 68) {
                self.removing = YES;
                BOOL removed = [self confirmClientRemoval];
                self.removing = NO;
                if (!removed && !self.children.count) {
                    self.requestedSettings = YES;
                    [self dispatchRequests];
                }
            }
            if (finished.terminationStatus == 70) {
                Notice(@"KienzleDoku konnte nicht starten", @"Bitte prüfen Sie, ob die App vollständig kopiert wurde und das externe Python 3.12 weiterhin funktioniert.");
            }
            if (setup) {
                self.configuring = NO;
                if (finished.terminationStatus == 0 && HasConfiguration()) {
                    if (self.deferPatient) {
                        Notice(@"Einrichtung abgeschlossen", @"Öffnen Sie den gewünschten Patienten jetzt erneut aus T2med.");
                    } else {
                        self.requestedSettings = YES;
                        [self dispatchRequests];
                    }
                }
            }
            if (!self.children.count) [NSApp terminate:nil];
        });
    };
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        self.configuring = NO;
        [self logStage:[NSString stringWithFormat:@"Prozessstart fehlgeschlagen: %ld",(long)error.code]];
        Notice(@"KienzleDoku konnte nicht starten", @"Bitte prüfen Sie Ihre externe Python-3.12-Installation.");
        if (!self.children.count) [NSApp terminate:nil];
        return;
    }
    [self.children addObject:task];
    if (input) {
        NSData *body = [url.absoluteString dataUsingEncoding:NSUTF8StringEncoding];
        if (![input.fileHandleForWriting writeData:body error:&error]) [self logStage:@"Übergabe des T2med-Aufrufs fehlgeschlagen."];
        [input.fileHandleForWriting closeFile];
    }
}
- (BOOL)confirmClientRemoval {
    NSFileManager *files = NSFileManager.defaultManager;
    NSURL *app = NSBundle.mainBundle.bundleURL.URLByStandardizingPath;
    NSString *parent = app.URLByDeletingLastPathComponent.URLByResolvingSymlinksInPath.path;
    NSURL *localApps = [NSURL fileURLWithPath:@"/Applications" isDirectory:YES];
    NSURL *userApps = [NSURL fileURLWithPath:[NSHomeDirectory() stringByAppendingPathComponent:@"Applications"] isDirectory:YES];
    NSArray *folders = @[localApps.URLByResolvingSymlinksInPath.path, userApps.URLByResolvingSymlinksInPath.path];
    NSNumber *isLink = nil;
    if (![app getResourceValue:&isLink forKey:NSURLIsSymbolicLinkKey error:NULL] || isLink.boolValue ||
        ![folders containsObject:parent] ||
        ![NSBundle.mainBundle.bundleIdentifier isEqual:@"de.kienzledoku.client.unified"]) {
        Notice(@"Client deinstallieren", @"Diese Kopie liegt außerhalb des Programme-Ordners. Sie können die App im Finder in den Papierkorb bewegen.");
        return NO;
    }
    if (self.children.count) {
        Notice(@"Aufnahme geöffnet", @"Bitte schließen Sie zuerst alle Record-Fenster.");
        return NO;
    }
    NSAlert *ask = [NSAlert new];
    ask.messageText = @"Client deinstallieren?";
    ask.informativeText = [NSString stringWithFormat:@"Diese App wird in den Papierkorb bewegt:\n%@\n\nDer Commander, seine Modelle und Python bleiben installiert.", app.path];
    NSButton *settings = [NSButton checkboxWithTitle:@"Auch meine Client-Einstellungen und meinen Commander-Zugang entfernen"
                                              target:nil action:nil];
    settings.state = NSControlStateValueOff;
    ask.accessoryView = settings;
    [ask addButtonWithTitle:@"Abbrechen"];
    [ask addButtonWithTitle:@"In den Papierkorb bewegen"];
    [NSApp activateIgnoringOtherApps:YES];
    if ([ask runModal] != NSAlertSecondButtonReturn) return NO;
    NSURL *support = ConfigDirectory();
    int dirfd = open(support.fileSystemRepresentation, O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    int fd = dirfd < 0 ? -1 : openat(dirfd, "update.lock", O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC, 0600);
    if (fd < 0 || flock(fd, LOCK_EX|LOCK_NB)) {
        if (fd >= 0) close(fd);
        if (dirfd >= 0) close(dirfd);
        Notice(@"Client wird verwendet", @"Bitte schließen Sie offene Aufnahmen, Einstellungen und Installationsvorgänge.");
        return NO;
    }
    NSError *error = nil;
    BOOL removed = [files trashItemAtURL:app resultingItemURL:NULL error:&error];
    BOOL settingsOK = YES;
    if (removed && settings.state == NSControlStateValueOn) {
        for (NSString *name in @[@"config.toml", @"commander.token"]) {
            struct stat st;
            const char *leaf = name.fileSystemRepresentation;
            if (fstatat(dirfd, leaf, &st, AT_SYMLINK_NOFOLLOW) == -1) {
                if (errno != ENOENT) settingsOK = NO;
            } else if (!S_ISREG(st.st_mode) || unlinkat(dirfd, leaf, 0) != 0) {
                settingsOK = NO;
            }
        }
        [NSUserDefaults.standardUserDefaults removeObjectForKey:@"ExternalCPython312"];
    }
    close(fd);
    close(dirfd);
    if (!removed) Notice(@"App konnte nicht entfernt werden", error.localizedDescription ?: @"Bitte prüfen Sie die Schreibrechte im Programme-Ordner.");
    if (!settingsOK) Notice(@"App im Papierkorb", @"Ein Teil der ausgewählten Client-Einstellungen konnte nicht entfernt werden.");
    return removed;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    if (!self.children.count) return NSTerminateNow;
    Notice(@"KienzleDoku ist geöffnet", @"Schließen Sie zuerst die geöffneten KienzleDoku-Fenster.");
    return NSTerminateCancel;
}
@end

int main(void) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        __attribute__((objc_precise_lifetime)) KDClient *client = [KDClient new]; app.delegate = client;
        [app run];
    }
    return 0;
}
