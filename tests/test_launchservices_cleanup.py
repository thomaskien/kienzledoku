"""Native Launch Services regression; touches only its unique temporary test app."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from installer.update_macos import unregister_old_app


@unittest.skipUnless(sys.platform=='darwin','Requires native macOS Launch Services')
class LaunchServicesCleanupTests(unittest.TestCase):
    def test_never_registered_registered_and_repeated_unregistration(self):
        tool='/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
        with tempfile.TemporaryDirectory(prefix='kienzledoku-ls-test-',dir='/private/tmp') as tmp:
            app=Path(tmp)/'Cleanup Test.app'
            (app/'Contents/MacOS').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier':'de.kienzledoku.cleanup-test.'+uuid.uuid4().hex,
                'CFBundleName':'Cleanup Test','CFBundleExecutable':'probe',
                'CFBundlePackageType':'APPL','CFBundleVersion':'1'}))
            shutil.copyfile('/usr/bin/true',app/'Contents/MacOS/probe')
            (app/'Contents/MacOS/probe').chmod(0o755)
            unregister_old_app(app)
            try:
                subprocess.run([tool,'-f',str(app)],check=True,capture_output=True,text=True,timeout=20)
                unregister_old_app(app)
                unregister_old_app(app)
            finally:
                unregister_old_app(app)


if __name__=='__main__':unittest.main()
