"""Offline tests for the standalone starter; never run a real installer."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('install_linux.sh').read_text()
SOURCE = SCRIPT.split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]
mod = types.ModuleType('linux_bootstrap_test')
exec(compile(SOURCE, 'install_linux.sh:python', 'exec'), mod.__dict__)


def asset(name, size=10, tag='v1.7.4'):
    return dict(name=name, size=size, state='uploaded', browser_download_url=
                'https://github.com/thomaskien/kienzledoku/releases/download/'+tag+'/'+name)


def release(version='1.7.4', prerelease=False):
    name='kienzledoku-'+version+'-linux-x86_64.tar.gz'
    return dict(tag_name='v'+version, prerelease=prerelease, draft=False,
                assets=[asset(name,tag='v'+version),asset(name+'.sha256',tag='v'+version)])


def archive_bytes(entries=None):
    root='kienzledoku-1.7.4-linux-x86_64'
    entries = entries or [(root+'/install_linux.sh', b'#!/bin/bash\nprintf "args:%s\\n" "$*"\nread -r reply\nprintf "stdin:%s\\n" "$reply"\nexit 7\n'),
                          (root+'/installer/linux_cli.py', b'# synthetic fixture only\n')]
    data=io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for name, content in entries:
            member=tarfile.TarInfo(name);member.size=len(content);member.mode=0o755
            tar.addfile(member,io.BytesIO(content))
    return data.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_no_release_fails(self):
        with self.assertRaisesRegex(mod.InstallError,'Noch kein freigegebenes'):
            mod.select_release([])

    def test_latest_linux_semver_not_windows_or_prerelease(self):
        windows=dict(tag_name='v9.0',assets=[asset('kienzledoku-9.0-windows-x64-setup.exe')])
        chosen,_=mod.select_release([release('1.7.9'),release('1.7.10'),windows,release('1.8.1',True)])
        self.assertIn('1.7.10',chosen['name'])

    def test_missing_new_checksum_does_not_fall_back(self):
        newest=release('1.8.1');newest['assets'].pop()
        with self.assertRaisesRegex(mod.InstallError,'SHA-256-Datei'):
            mod.select_release([release(),newest])

    def test_external_download_host_is_rejected(self):
        item=release();item['assets'][0]['browser_download_url']='https://example.com/payload'
        with self.assertRaisesRegex(mod.InstallError,'Downloadziel'):
            mod.select_release([item])

    def test_ambiguous_version_is_rejected(self):
        with self.assertRaisesRegex(mod.InstallError,'mehrfach'):
            mod.select_release([release(),release()])

    def test_size_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(mod,'request',return_value=io.BytesIO(b'short')):
            with self.assertRaisesRegex(mod.InstallError,'unvollständig'):
                mod.download(asset('test'),Path(folder)/'test',100)

    def test_checksum_name_and_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'archive.tar.gz';checksum=Path(folder)/'archive.sha256'
            archive.write_bytes(b'valid')
            checksum.write_text(hashlib.sha256(b'valid').hexdigest()+'  other.tar.gz\n')
            with self.assertRaisesRegex(mod.InstallError,'passt nicht'):mod.verify_checksum(archive,checksum)
            checksum.write_text('0'*64+'  '+archive.name+'\n')
            with self.assertRaisesRegex(mod.InstallError,'fehlgeschlagen'):mod.verify_checksum(archive,checksum)
            checksum.write_text(hashlib.sha256(b'valid').hexdigest()+'  '+archive.name+'\n')
            mod.verify_checksum(archive,checksum)

    def test_archive_traversal_is_rejected_before_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'kienzledoku-1.7.4-linux-x86_64.tar.gz'
            archive.write_bytes(archive_bytes([('kienzledoku-1.7.4-linux-x86_64/../escape',b'x')]))
            with self.assertRaises(mod.InstallError):mod.extract_archive(archive,Path(folder))
            self.assertFalse((Path(folder)/'escape').exists())

    def test_archive_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'kienzledoku-1.7.4-linux-x86_64.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                link=tarfile.TarInfo('kienzledoku-1.7.4-linux-x86_64/link')
                link.type=tarfile.SYMTYPE;link.linkname='/tmp';tar.addfile(link)
            with self.assertRaises(mod.InstallError):mod.extract_archive(archive,Path(folder))

    def test_root_client_rejected_before_network(self):
        with patch.object(mod.sys,'platform','linux'),patch.object(mod.platform,'machine',return_value='x86_64'),patch.object(mod.os,'geteuid',return_value=0),patch.object(mod,'releases') as network:
            with self.assertRaisesRegex(mod.InstallError,'Als root'):mod.main(['--components','both'])
            network.assert_not_called()

    def test_real_shell_preserves_terminal_arguments_and_exit_code(self):
        data=archive_bytes();item=release();name=item['assets'][0]['name']
        checksum=(hashlib.sha256(data).hexdigest()+'  '+name+'\n').encode()
        item['assets'][0]['size']=len(data);item['assets'][1]['size']=len(checksum)
        payloads={a['browser_download_url']:d for a,d in zip(item['assets'],[data,checksum])}
        injection=('\nimport io\nsys.platform="linux"\nplatform.machine=lambda:"x86_64"\nos.geteuid=lambda:1000\n'
                   +'releases=lambda:'+repr([item])+'\n'
                   +'_fixtures='+repr(payloads)+'\nrequest=lambda url:io.BytesIO(_fixtures[url])\n')
        script=SCRIPT.replace("\nif __name__ == '__main__':",injection+"\nif __name__ == '__main__':")
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.sh';path.write_text(script)
            result=subprocess.run(['bash',str(path),'--components','server'],input='terminal input\n',text=True,capture_output=True)
        self.assertEqual(result.returncode,7,result.stderr)
        self.assertIn('args:--components server',result.stdout)
        self.assertIn('stdin:terminal input',result.stdout)
        self.assertIn('SHA-256-Prüfung erfolgreich',result.stdout)


if __name__ == '__main__':
    unittest.main()
