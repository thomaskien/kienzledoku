// Exercise the shipped native confirmation and locking with an isolated home.
// Replace only modal interaction, the bundle URL and the OS Trash destination.
#import <Cocoa/Cocoa.h>
#define NSHomeDirectory() (NSProcessInfo.processInfo.environment[@"CFFIXED_USER_HOME"])
#define main KienzleClientMain
#import "../installer/macos_single_app/Client.m"
#undef main
#import <objc/runtime.h>
static NSURL *testApp, *testTrash;
static BOOL confirm, cleanup;
@interface NSBundle (KDTest)
- (NSURL *)kdURL;
- (NSString *)kdID;
@end
@implementation NSBundle (KDTest)
- (NSURL *)kdURL { return self == NSBundle.mainBundle ? testApp : [self kdURL]; }
- (NSString *)kdID { return self == NSBundle.mainBundle ? @"de.kienzledoku.client.unified" : [self kdID]; }
@end
@interface NSAlert (KDTest)
- (NSModalResponse)kdModal;
@end
@implementation NSAlert (KDTest)
- (NSModalResponse)kdModal {
    fprintf(stderr,"Test dialog: %s\n", self.messageText.UTF8String);
    if ([self.messageText isEqual:@"Client deinstallieren?"]) {
        NSButton *toggle = (NSButton *)self.accessoryView;
        NSCAssert(toggle.state == NSControlStateValueOff, @"must default to keep settings");
        toggle.state = cleanup ? NSControlStateValueOn : NSControlStateValueOff;
        return confirm ? NSAlertSecondButtonReturn : NSAlertFirstButtonReturn;
    }
    return NSAlertFirstButtonReturn;
}
@end
@interface NSFileManager (KDTest)
- (BOOL)kdTrash:(NSURL *)url result:(NSURL **)result error:(NSError **)error;
@end
@implementation NSFileManager (KDTest)
- (BOOL)kdTrash:(NSURL *)url result:(NSURL **)result error:(NSError **)error {
    NSCAssert([url.URLByResolvingSymlinksInPath.path isEqual:testApp.URLByResolvingSymlinksInPath.path], @"unexpected target");
    return [self moveItemAtURL:url toURL:testTrash error:error];
}
@end
static void swap(Class c, SEL original, SEL method) {
    method_exchangeImplementations(class_getInstanceMethod(c,original),class_getInstanceMethod(c,method));
}
int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        NSString *home = NSHomeDirectory();
        if (![home hasPrefix:@"/private/tmp/kd183-check/uninstall-"]) return 2;
        NSURL *root = [NSURL fileURLWithPath:home isDirectory:YES];
        testApp = [root URLByAppendingPathComponent:@"Applications/KienzleDoku.app" isDirectory:YES];
        testTrash = [root URLByAppendingPathComponent:@"trashed.app" isDirectory:YES];
        NSFileManager *fs = NSFileManager.defaultManager;
        NSURL *config = ConfigDirectory();
        [fs createDirectoryAtURL:testApp withIntermediateDirectories:YES attributes:nil error:NULL];
        [fs createDirectoryAtURL:config withIntermediateDirectories:YES attributes:nil error:NULL];
        for (NSString *name in @[@"config.toml",@"commander.token",@"keep-server"]) {
            [@"test" writeToURL:[config URLByAppendingPathComponent:name] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
        }
        swap(NSBundle.class,@selector(bundleURL),@selector(kdURL));
        swap(NSBundle.class,@selector(bundleIdentifier),@selector(kdID));
        swap(NSAlert.class,@selector(runModal),@selector(kdModal));
        swap(NSFileManager.class,@selector(trashItemAtURL:resultingItemURL:error:),@selector(kdTrash:result:error:));
        KDClient *client = [KDClient new];
        NSCAssert(![client confirmClientRemoval],@"cancel");
        confirm = YES;
        int lock = open([config URLByAppendingPathComponent:@"update.lock"].fileSystemRepresentation,O_RDWR|O_CREAT,0600);
        NSCAssert(flock(lock,LOCK_SH|LOCK_NB)==0,@"test recording lock");
        NSCAssert(![client confirmClientRemoval] && [fs fileExistsAtPath:testApp.path],@"active recording");
        close(lock);
        NSCAssert([client confirmClientRemoval] && [fs fileExistsAtPath:testTrash.path],@"move to trash");
        NSCAssert([fs fileExistsAtPath:[config URLByAppendingPathComponent:@"commander.token"].path],@"keep settings");
        [fs moveItemAtURL:testTrash toURL:testApp error:NULL];
        cleanup = YES;
        NSCAssert([client confirmClientRemoval],@"remove app and preferences");
        NSCAssert(![fs fileExistsAtPath:[config URLByAppendingPathComponent:@"commander.token"].path],@"remove token");
        NSCAssert(![fs fileExistsAtPath:[config URLByAppendingPathComponent:@"config.toml"].path],@"remove config");
        NSCAssert([fs fileExistsAtPath:[config URLByAppendingPathComponent:@"keep-server"].path],@"preserve server files");
        puts("Uninstall selection, cancellation, recording lock, both confirmation paths OK");
    }
}
