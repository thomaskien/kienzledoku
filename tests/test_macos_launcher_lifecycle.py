"""Exercise native launcher lifetime with synthetic child processes only."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='darwin','Native macOS launcher')
class MacLauncherLifecycleTests(unittest.TestCase):
    def test_record_and_connect_exit_only_after_last_child(self):
        with tempfile.TemporaryDirectory(prefix='kienzledoku-launcher-test-') as directory:
            base=Path(directory)
            driver=base/'driver.m'
            driver.write_text('#define main KienzledokuOriginalMain\n'+
                              (ROOT/'native/KienzledokuApp.m').read_text()+
                              '''\n#undef main
int main(void) {
    @autoreleasepool {
        NSApplication *app=[NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        RecordLauncher *delegate=[RecordLauncher new];
        delegate.receivedURL=YES;
        delegate.tasks=[NSMutableArray new];
        app.delegate=delegate;
        [delegate launch:@"synthetic-fast"];
        [delegate launch:@"synthetic-slow"];
        [app run];
    }
    return 0;
}
''')
            for mode in ('record','connect'):
                with self.subTest(mode=mode):
                    root=base/mode;root.mkdir()
                    # No credentials, network, microphone or real Record imports.
                    stub='''import sys,time
from pathlib import Path
value=sys.stdin.read()
assert sys.argv[1:]==['--deep-link-stdin']
time.sleep(.1 if value=='synthetic-fast' else .6)
with Path('completed').open('a') as out:out.write(value+'\\n')
'''
                    (root/'kienzledoku.py').write_text(stub)
                    connect=root/'kienzleconnect'
                    connect.write_text('#!'+sys.executable+'\n'+stub);connect.chmod(0o700)
                    app=root/'Test Launcher.app';contents=app/'Contents'
                    (contents/'MacOS').mkdir(parents=True)
                    binary=contents/'MacOS/launcher'
                    (contents/'Info.plist').write_bytes(plistlib.dumps(dict(
                        CFBundleIdentifier='de.kienzledoku.synthetic.'+mode,
                        CFBundleExecutable='launcher',CFBundlePackageType='APPL',
                        KienzledokuRoot=str(root),KienzledokuPython=sys.executable)))
                    subprocess.run(['/usr/bin/clang','-fobjc-arc','-framework','Cocoa',
                                    '-DKIENZLEDOKU_LAUNCHER_MODE="'+mode+'"',driver,'-o',binary],
                                   check=True,capture_output=True)
                    subprocess.run(['/usr/bin/codesign','--force','--sign','-',app],
                                   check=True,capture_output=True)
                    process=subprocess.Popen([str(binary)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    try:
                        _,error=process.communicate(timeout=8)
                        self.assertEqual(0,process.returncode,error.decode(errors='replace'))
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                    self.assertEqual(['synthetic-fast','synthetic-slow'],(root/'completed').read_text().splitlines())


if __name__=='__main__':unittest.main()
