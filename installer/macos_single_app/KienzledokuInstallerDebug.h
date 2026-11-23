#import <Foundation/Foundation.h>

#ifdef KIENZLEDOKU_INSTALLER_DEBUG_DESKTOP
#import <Security/Security.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/utsname.h>
#include <sys/xattr.h>
#include <unistd.h>

static int KDLogFD = -1;
static NSObject *KDLogLock;
static NSString *KDLogPath;
static NSString *KDLogFailure;
static NSString *KDStage = @"main entered";
static NSUInteger KDLogBytes;
static dispatch_source_t KDHeartbeat;

// No environment, configuration, request bodies or backend URL are recorded.
// Runtime output is limited to our structured diagnostic records. Arbitrary
// Python stderr can contain credentials and is counted, never copied verbatim.
static NSString *KDClean(NSString *value) {
    NSString *text = value ?: @"";
    text = [text stringByReplacingOccurrencesOfString:NSHomeDirectory() withString:@"~"];
    text = [text stringByReplacingOccurrencesOfString:@"\n" withString:@" "];
    text = [text stringByReplacingOccurrencesOfString:@"\r" withString:@" "];
    return text.length > 1600 ? [[text substringToIndex:1600] stringByAppendingString:@" [truncated]"] : text;
}

static void KDLog(NSString *event) {
    if (KDLogFD < 0) return;
    @synchronized (KDLogLock) {
        const NSUInteger limit = 4 * 1024 * 1024;
        if (KDLogBytes >= limit) return;
        NSString *line = [NSString stringWithFormat:@"%@ [native] %@\n", NSDate.date, KDClean(event)];
        NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];
        if (KDLogBytes + data.length > limit) {
            data = [@"[native] Log limit reached (4 MiB).\n" dataUsingEncoding:NSUTF8StringEncoding];
            KDLogBytes = limit;
        }
        const char *bytes = data.bytes;
        NSUInteger remaining = data.length;
        while (remaining > 0) {
            ssize_t written = write(KDLogFD, bytes, remaining);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) break;
            bytes += written; remaining -= (NSUInteger)written;
        }
        KDLogBytes += data.length;
        fsync(KDLogFD);
    }
}

static void KDSetStage(NSString *stage) {
    @synchronized (KDLogLock) { KDStage = [stage copy]; }
    KDLog([@"stage: " stringByAppendingString:stage]);
}

static void KDLogError(NSString *event, NSError *error) {
    // NSError.userInfo may contain URLs/tokens; only stable code/domain.
    KDLog([NSString stringWithFormat:@"%@: domain=%@ code=%ld", event,
           error.domain ?: @"none", (long)error.code]);
}

static void KDInspectPath(NSString *label, NSURL *url) {
    if (!url) { KDLog([label stringByAppendingString:@": missing URL"]); return; }
    NSString *path = url.path;
    NSFileManager *fm = NSFileManager.defaultManager;
    struct stat st = {0}; int result = stat(path.fileSystemRepresentation, &st);
    ssize_t quarantine = getxattr(path.fileSystemRepresentation, "com.apple.quarantine", NULL, 0, 0, 0);
    int attributeError = quarantine < 0 ? errno : 0;
    KDLog([NSString stringWithFormat:@"%@: path=%@ exists=%d readable=%d executable=%d stat=%d mode=%o bytes=%lld quarantine_bytes=%ld quarantine_errno=%d",
           label, path, [fm fileExistsAtPath:path], [fm isReadableFileAtPath:path],
           [fm isExecutableFileAtPath:path], result, st.st_mode & 0777,
           (long long)st.st_size, (long)quarantine, attributeError]);
}

static void KDInspectSignature(NSString *label, NSURL *url) {
    if (!url) return;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        @autoreleasepool {
            KDLog([label stringByAppendingString:@": signature check begins"]);
            SecStaticCodeRef code = NULL;
            OSStatus status = SecStaticCodeCreateWithPath((__bridge CFURLRef)url, kSecCSDefaultFlags, &code);
            if (status == errSecSuccess) {
                status = SecStaticCodeCheckValidity(code, kSecCSCheckAllArchitectures | kSecCSStrictValidate, NULL);
            }
            KDLog([NSString stringWithFormat:@"%@: signature OSStatus=%d (0=valid; no notarization assessment)", label, (int)status]);
            if (code) CFRelease(code);
        }
    });
}

static void KDInitialize(void) {
    KDLogLock = [NSObject new];
    NSURL *desktop = [NSFileManager.defaultManager URLsForDirectory:NSDesktopDirectory inDomains:NSUserDomainMask].firstObject;
    NSDateFormatter *formatter = [NSDateFormatter new];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.dateFormat = @"yyyy-MM-dd_HH-mm-ss";
    NSString *stamp = [formatter stringFromDate:NSDate.date];
    NSString *name = [NSString stringWithFormat:@"KienzleDoku-1.8.3-Installation-Debug-%@-%d-%@.log", stamp, getpid(), [NSUUID.UUID.UUIDString substringToIndex:8]];
    KDLogPath = [[desktop URLByAppendingPathComponent:name] path];
    if (KDLogPath) KDLogFD = open(KDLogPath.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_APPEND | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (KDLogFD < 0) {
        KDLogFailure = [NSString stringWithFormat:@"Die Debug-Logdatei konnte nicht auf dem Schreibtisch angelegt werden (Fehler %d). Bitte den Schreibtischzugriff für den Installer erlauben und erneut starten.", errno];
        return;
    }
    KDLog(@"KienzleDoku 1.8.3 ARM64 — Commander installer with external CPython 3.12.");
    KDLog(@"Scope: startup checkpoints, technical error codes and stack locations; no configuration values, tokens, patient data, request bodies or raw subprocess output.");
    struct utsname machine; uname(&machine);
    int arm = 0, translated = 0; size_t size = sizeof(int);
    sysctlbyname("hw.optional.arm64", &arm, &size, NULL, 0); size = sizeof(int);
    sysctlbyname("sysctl.proc_translated", &translated, &size, NULL, 0);
    KDLog([NSString stringWithFormat:@"OS=%@ machine=%s arm64_capable=%d translated=%d RAM_bytes=%llu pid=%d uid=%d euid=%d",
           NSProcessInfo.processInfo.operatingSystemVersionString, machine.machine, arm, translated,
           NSProcessInfo.processInfo.physicalMemory, getpid(), getuid(), geteuid()]);
    KDInspectPath(@"app", NSBundle.mainBundle.bundleURL);
    KDInspectPath(@"native executable", NSBundle.mainBundle.executableURL);
    KDHeartbeat = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
    dispatch_source_set_timer(KDHeartbeat, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), 15 * NSEC_PER_SEC, NSEC_PER_SEC);
    dispatch_source_set_event_handler(KDHeartbeat, ^{
        @autoreleasepool {
            NSString *stage;
            @synchronized (KDLogLock) { stage = KDStage; }
            KDLog([@"heartbeat: " stringByAppendingString:stage]);
        }
    });
    dispatch_resume(KDHeartbeat);
}

static NSString *KDDebugNotice(void) {
    return KDLogFailure ?: [NSString stringWithFormat:@"Debug-Protokoll auf dem Schreibtisch:\n%@", KDLogPath.lastPathComponent];
}

static void KDRecordPython(NSData *data) {
    // Only records generated by the allowlisted Python diagnostic wrapper.
    // Keep line fragments across readability callbacks without exposing raw data.
    static NSMutableData *pending;
    @synchronized (KDLogLock) {
        if (!pending) pending = [NSMutableData data];
        [pending appendData:data];
        for (;;) {
            const unsigned char *bytes = pending.bytes;
            NSUInteger index = 0;
            while (index < pending.length && bytes[index] != '\n') index++;
            if (index == pending.length) break;
            NSData *lineData = [pending subdataWithRange:NSMakeRange(0, index)];
            NSString *line = [[NSString alloc] initWithData:lineData encoding:NSUTF8StringEncoding];
            if ([line hasPrefix:@"[KDDEBUG] "]) KDLog(line);
            else KDLog([NSString stringWithFormat:@"python stderr: %lu bytes (content omitted)", (unsigned long)lineData.length]);
            [pending replaceBytesInRange:NSMakeRange(0, index + 1) withBytes:NULL length:0];
        }
        if (pending.length > 16384) { KDLog(@"python stderr: oversized fragment omitted"); [pending setLength:0]; }
    }
}
#else
static void KDInitialize(void) {}
static void KDLog(NSString *event) { (void)event; }
static void KDSetStage(NSString *stage) { (void)stage; }
static void KDLogError(NSString *event, NSError *error) { (void)event; (void)error; }
static void KDInspectPath(NSString *label, NSURL *url) { (void)label; (void)url; }
static void KDInspectSignature(NSString *label, NSURL *url) { (void)label; (void)url; }
static void KDRecordPython(NSData *data) { (void)data; }
#endif
