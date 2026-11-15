#import <Cocoa/Cocoa.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#ifndef KIENZLEDOKU_LAUNCHER_MODE
#define KIENZLEDOKU_LAUNCHER_MODE "record"
#endif
// Compile each app separately: macOS local-network privacy uses the Mach-O
// UUID as part of app identity, so Record and Connect must not share a binary.
static NSString *const KienzledokuLauncherMode = @KIENZLEDOKU_LAUNCHER_MODE;
@interface RecordLauncher : NSObject <NSApplicationDelegate>
@property BOOL receivedURL;
@property(strong) NSMutableArray<NSTask *> *tasks;
@end
@implementation RecordLauncher
- (void)finishIfIdle {
    if(self.tasks.count==0) [NSApp terminate:nil];
}
- (void)launch:(NSString *)url {
    NSDictionary *info=NSBundle.mainBundle.infoDictionary;
    NSString *root=info[@"KienzledokuRoot"], *python=info[@"KienzledokuPython"];
    NSString *lockPath=info[@"KienzledokuUpdateLock"];
    NSFileHandle *updateLease=nil;
    if(lockPath){
        int fd=open(lockPath.fileSystemRepresentation,O_RDWR|O_CREAT|O_NOFOLLOW,0600);
        if(fd<0 || flock(fd,LOCK_SH|LOCK_NB)!=0){
            if(fd>=0)close(fd);
            NSAlert *alert=[NSAlert new];alert.messageText=@"Kienzledoku wird aktualisiert";
            alert.informativeText=@"Bitte den Abschluss der Installation abwarten und anschließend erneut aus T2med öffnen.";
            [alert runModal];[self finishIfIdle];return;
        }
        updateLease=[[NSFileHandle alloc] initWithFileDescriptor:fd closeOnDealloc:YES];
    }
    NSTask *task=[NSTask new]; task.currentDirectoryURL=[NSURL fileURLWithPath:root];
    NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];
    [env removeObjectsForKeys:@[@"PYTHONHOME", @"PYTHONPATH", @"DYLD_LIBRARY_PATH", @"DYLD_FALLBACK_LIBRARY_PATH"]];
    env[@"KIENZLEDOKU_PYTHON"]=python; env[@"PYTHONDONTWRITEBYTECODE"]=@"1";
    task.environment=env;
    if(url && [KienzledokuLauncherMode isEqualToString:@"connect"]){
        task.executableURL=[NSURL fileURLWithPath:[root stringByAppendingPathComponent:@"kienzleconnect"]];
        task.arguments=@[@"--deep-link-stdin"];
    } else {
        task.executableURL=[NSURL fileURLWithPath:python];
        task.arguments=@[[root stringByAppendingPathComponent:@"kienzledoku.py"],url?@"--deep-link-stdin":@"--settings"];
    }
    NSPipe *input=[NSPipe pipe]; task.standardInput=input;
    task.standardOutput=NSFileHandle.fileHandleWithNullDevice;
    task.standardError=NSFileHandle.fileHandleWithNullDevice;
    __weak RecordLauncher *weakSelf=self;
    task.terminationHandler=^(NSTask *completed) {
        [updateLease closeFile];
        dispatch_async(dispatch_get_main_queue(), ^{
            RecordLauncher *owner=weakSelf;
            if(!owner) return;
            [owner.tasks removeObject:completed];
            [owner finishIfIdle];
        });
    };
    NSError *error=nil;
    if(![task launchAndReturnError:&error]){
        [updateLease closeFile];
        NSAlert *alert=[NSAlert new]; alert.messageText=@"kienzledoku konnte nicht gestartet werden";
        BOOL rootExists=[NSFileManager.defaultManager fileExistsAtPath:root];
        alert.informativeText=rootExists
            ? [NSString stringWithFormat:@"Der lokale Programmstart ist fehlgeschlagen (%@, Code %ld). Bitte die Client-Installation prüfen.",error.domain ?: @"Startfehler",(long)error.code]
            : @"Dieser Starter gehört zu einer inzwischen entfernten Installation. Er wird nach OK geschlossen. Bitte Kienzledoku anschließend erneut aus T2med öffnen.";
        [alert runModal]; [self finishIfIdle]; return;
    }
    if(url) [input.fileHandleForWriting writeData:[url dataUsingEncoding:NSUTF8StringEncoding]];
    [input.fileHandleForWriting closeFile]; [self.tasks addObject:task];
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    if(!self.tasks) self.tasks=[NSMutableArray new];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(0.5*NSEC_PER_SEC)),dispatch_get_main_queue(),^{if(!self.receivedURL)[self launch:nil];});
}
- (void)application:(NSApplication *)app openURLs:(NSArray<NSURL *> *)urls {
    self.receivedURL=YES; if(!self.tasks)self.tasks=[NSMutableArray new];
    for(NSURL *url in urls) [self launch:url.absoluteString];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
    if(!visible)[self launch:nil]; return YES;
}
@end
int main(int argc,const char *argv[]){
    @autoreleasepool {
        NSApplication *app=[NSApplication sharedApplication]; [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        RecordLauncher *delegate=[RecordLauncher new]; app.delegate=delegate; [app run];
    }return 0;
}
