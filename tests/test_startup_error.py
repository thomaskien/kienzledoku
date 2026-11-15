"""Startup failures stay visible without leaking exception/deep-link details."""
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import kienzledoku as record
from kienzledoku_commander_client import CommanderRequestError


class StartupErrorTests(unittest.TestCase):
    def test_mac_uses_only_allowlisted_error_categories(self):
        for error,category in [(RuntimeError('private-secret'),'generic'),
                               (CommanderRequestError('private-secret'),'commander'),
                               (CommanderRequestError('private-secret',401),'commander-auth')]:
            with self.subTest(category=category),mock.patch.object(record.sys,'platform','darwin'), \
                 mock.patch.object(record.subprocess,'run') as run:
                record.notify_start_failure(error)
                self.assertEqual(['--startup-error',category],run.call_args.args[0][-2:])
                self.assertNotIn('private-secret',str(run.call_args))

    def test_main_reports_commander_start_failure(self):
        error=CommanderRequestError('synthetic')
        with mock.patch.object(sys,'argv',['record','--deep-link','synthetic']), \
             mock.patch.object(record,'run_session',side_effect=error), \
             mock.patch.object(record,'safe_log'),mock.patch.object(record,'notify_start_failure') as notify, \
             mock.patch.object(sys,'stderr'):
            self.assertEqual(1,record.main())
        notify.assert_called_once_with(error)

    def test_failed_settings_read_closes_transport_and_releases_session(self):
        cfg=record.record_config.defaults()
        link=dict(context_id='synthetic',oauth_token='synthetic',
                  fhir_base_url=cfg['connection']['target'],scheme='kienzledoku')
        error=CommanderRequestError('synthetic')
        with mock.patch.object(record,'parse_deep_link',return_value=link), \
             mock.patch.object(record,'acquire_record_session'), \
             mock.patch.object(record,'cleanup_legacy_patient_data'), \
             mock.patch.object(record,'safe_log'), \
             mock.patch.object(record.record_config,'load',return_value=cfg), \
             mock.patch.object(record,'get_api_key',return_value=('synthetic','test')), \
             mock.patch.object(record,'T2medFhirClient') as client, \
             mock.patch.object(record,'SpeechRecognitionManager') as speech, \
             mock.patch.object(record,'unregister_window') as release, \
             mock.patch.object(record,'open_ui_window') as window:
            client.return_value.proxy=False
            speech.return_value.load_documentation_settings.side_effect=error
            with self.assertRaises(CommanderRequestError):record.run_session('synthetic')
            client.return_value.close.assert_called_once_with()
            release.assert_called_once_with();window.assert_not_called()
            speech.return_value.start.assert_not_called()

    @unittest.skipUnless(sys.platform=='darwin','Cocoa startup dialog')
    def test_native_entry_builds_readable_dialog_without_rendering_user_ui(self):
        # Exercise the actual native command path; replace only the modal UI
        # presentation so unattended tests cannot leave a dialog on the Mac.
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);source=path/'test.m';binary=path/'test'
            source.write_text('#define main original_main\n#include "'+str(root/'native/KienzledokuWindow.m')+'"\n#undef main\n'+r'''
#import <objc/runtime.h>
@interface NSAlert (StartupTest)
- (NSModalResponse)testModal;
@end
@implementation NSAlert (StartupTest)
- (NSModalResponse)testModal {
    if (!self.messageText.length || ![self.informativeText containsString:@"Commander"] ||
        ![self.informativeText containsString:@"keine Aufnahme"]) exit(3);
    puts("native startup dialog OK");return NSAlertFirstButtonReturn;
}
@end
int main(void) {
    method_exchangeImplementations(class_getInstanceMethod(NSAlert.class,@selector(runModal)),
                                   class_getInstanceMethod(NSAlert.class,@selector(testModal)));
    const char *args[]={"test","--startup-error","commander"};
    return original_main(3,args);
}
''')
            subprocess.run(['/usr/bin/clang','-fobjc-arc','-framework','Cocoa','-framework','WebKit',str(source),'-o',str(binary)],check=True,capture_output=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True,timeout=10)
            self.assertIn('native startup dialog OK',result.stdout)


if __name__=='__main__':unittest.main()
