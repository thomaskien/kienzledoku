import json
import hashlib
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from unittest.mock import Mock, patch

from installer import locked_dependencies as dep


class DependencyTests(unittest.TestCase):
    def test_all_release_locks_are_complete_pins_with_hashes(self):
        directory = Path(__file__).resolve().parents[1]/'installer/dependency-locks'
        self.assertEqual(len(list(directory.glob('*.txt'))), 4)
        for path in directory.glob('*.txt'):
            digest, packages = dep.read_lock(path)
            self.assertEqual(len(digest), 64)
            self.assertGreater(len(packages), 30)
            self.assertTrue(all(p['approved_sha256'] for p in packages.values()))

    def test_existing_digest_does_not_hide_changed_installed_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'linux-asr-py312.txt'; report=Path(tmp)/'inventory.json'
            lock.write_text('example==1.0 --hash=sha256:'+'a'*64+'\n')
            digest, packages=dep.read_lock(lock)
            report.write_text(json.dumps({'lock_sha256':digest}))
            wrong=dict(python=[3,12],platform='linux',machine='x86_64',packages={'example':'2.0'})
            right=dict(wrong,packages={'example':'1.0'})
            run=Mock()
            with patch.object(dep,'snapshot',side_effect=[wrong,right]):
                dep.install_locked('/synthetic/python',lock,report,run)
            command=run.call_args_list[0].args[0]
            self.assertIn('--require-hashes',command)
            self.assertIn('--force-reinstall',command)
            self.assertIn('--only-binary=:all:',command)
            self.assertEqual(json.loads(report.read_text())['distributions'],packages)

    def test_bad_lock_or_wrong_platform_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'bad.txt';lock.write_text('example>=1.0\n')
            with self.assertRaises(ValueError):dep.read_lock(lock)
        with self.assertRaises(ValueError):
            dep.verify_snapshot(dict(python=[3,14],platform='linux',machine='x86_64'),{},'linux-asr-py312.txt')

    def test_extra_package_is_detected(self):
        with self.assertRaises(ValueError):
            dep.verify_snapshot(dict(python=[3,12],platform='linux',machine='x86_64',packages={'unexpected':'1'}),{},'linux-asr-py312.txt')

    def test_wrong_target_never_runs_pip(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'linux-asr-py312.txt'
            lock.write_text('example==1.0 --hash=sha256:'+'a'*64+'\n')
            run=Mock()
            with patch.object(dep,'snapshot',return_value=dict(python=[3,12],platform='darwin',machine='arm64')),self.assertRaises(ValueError):
                dep.install_locked('/synthetic/python',lock,Path(tmp)/'report.json',run)
            run.assert_not_called()

    @unittest.skipUnless(sys.version_info[:2]==(3,12) and (sys.platform,platform.machine()) in {('darwin','arm64'),('linux','x86_64')},'Python 3.12 server target needed')
    def test_two_fresh_installs_match_and_changed_wheel_is_rejected(self):
        # Exercise real pip and inventory output, offline, with a harmless fixture wheel.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); wheel=root/'audit_example-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                for name,value in {
                    'audit_example.py':'VALUE = 1\n',
                    'audit_example-1.0.dist-info/METADATA':'Metadata-Version: 2.1\nName: audit-example\nVersion: 1.0\n',
                    'audit_example-1.0.dist-info/WHEEL':'Wheel-Version: 1.0\nGenerator: synthetic-audit\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
                    'audit_example-1.0.dist-info/RECORD':''}.items():archive.writestr(name,value)
            lock=root/('macos-asr-py312.txt' if sys.platform=='darwin' else 'linux-asr-py312.txt')
            lock.write_text('audit-example==1.0 --hash=sha256:'+hashlib.sha256(wheel.read_bytes()).hexdigest()+'\n')
            reports=[]
            def run(command,env=None):
                if 'install' in command:command=[*command,'--no-index','--find-links',str(root)]
                subprocess.run(list(map(str,command)),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
            for index in range(2):
                target=root/str(index);venv.EnvBuilder(with_pip=True).create(target)
                reports.append(dep.install_locked(target/'bin/python',lock,root/f'report-{index}.json',run))
            self.assertEqual(reports[0],reports[1])
            with wheel.open('ab') as handle:handle.write(b'SYNTHETIC TAMPER')
            with self.assertRaises(subprocess.CalledProcessError):
                dep.install_locked(root/'0/bin/python',lock,root/'tampered.json',run)
            self.assertFalse((root/'tampered.json').exists())

    def test_failed_verification_does_not_publish_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'linux-asr-py312.txt';report=Path(tmp)/'inventory.json'
            lock.write_text('example==1.0 --hash=sha256:'+'a'*64+'\n')
            bad=dict(python=[3,12],platform='linux',machine='x86_64',packages={})
            with patch.object(dep,'snapshot',return_value=bad),self.assertRaises(ValueError):
                dep.install_locked('/synthetic/python',lock,report,Mock())
            self.assertFalse(report.exists())
