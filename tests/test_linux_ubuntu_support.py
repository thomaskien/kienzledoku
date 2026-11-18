import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import kienzledoku_linux_runtime as runtime


class UbuntuSupportTests(unittest.TestCase):
    def test_exact_release_and_architecture(self):
        for value in ('24.04', '26.04'):
            for quote in ('', '"', "'"):
                self.assertEqual(value, runtime.ubuntu_version('ID=ubuntu\nVERSION_ID='+quote+value+quote+'\n', 'x86_64'))
        for release in ('ID=ubuntu\nVERSION_ID=26.10', 'ID=notubuntu\nVERSION_ID=26.04',
                        'ID=debian\nID_LIKE=ubuntu\nVERSION_ID=26.04',
                        'ID=ubuntu\nVERSION_ID=24.04\nVERSION_ID=26.04'):
            with self.assertRaises(ValueError):runtime.ubuntu_version(release,'x86_64')
        with self.assertRaises(ValueError):runtime.ubuntu_version('ID=ubuntu\nVERSION_ID=26.04','aarch64')

    def test_2404_uses_system_python_and_never_downloads(self):
        with patch.object(runtime,'python_info',return_value=([3,12,3],'/usr')),patch.object(runtime,'download') as download:
            self.assertEqual(Path('/usr/bin/python3.12'),runtime.ensure_python('/unused','24.04'))
            download.assert_not_called()

    def test_download_mismatch_is_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(runtime.urllib.request,'urlopen',return_value=io.BytesIO(b'bad')):
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                runtime.ensure_python(Path(temp)/'runtime','26.04')
            self.assertFalse((Path(temp)/'runtime').exists())

    def test_unknown_runtime_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'runtime';target.mkdir();(target/'mine').write_text('keep')
            with self.assertRaisesRegex(ValueError,'Unbekannte'):runtime.ensure_python(target,'26.04')
            self.assertEqual('keep',(target/'mine').read_text())
            link=Path(temp)/'link';link.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'Verknüpfter'):runtime.ensure_python(link,'26.04')

    def test_existing_verified_runtime_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'runtime';target.mkdir()
            (target/'.kienzledoku-python.json').write_text(json.dumps(runtime.IDENTITY))
            with patch.object(runtime,'python_info',return_value=([3,12,16],str(target))),patch.object(runtime,'download') as download:
                self.assertEqual(target/'bin/python3.12',runtime.ensure_python(target,'26.04'))
                download.assert_not_called()

    def test_broken_venv_after_os_upgrade_is_rebuilt_and_old_code_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'asr-venv';target.mkdir();(target/'pyvenv.cfg').touch();(target/'old.py').touch()
            def create(*args,**kwargs):
                target.mkdir();(target/'pyvenv.cfg').touch();(target/'new.py').touch()
            with patch.object(runtime,'python_info',side_effect=[([3,12,16],'/owned'),None]),patch.object(runtime.subprocess,'run',side_effect=create):
                runtime.ensure_venv('/owned/bin/python3.12',target)
            self.assertTrue((target/'new.py').exists());self.assertFalse((target/'old.py').exists())
            self.assertEqual(['asr-venv'],[p.name for p in Path(temp).iterdir()])

    def test_failed_venv_creation_restores_previous(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'asr-venv';target.mkdir();(target/'pyvenv.cfg').touch();(target/'old.py').touch()
            with patch.object(runtime,'python_info',side_effect=[([3,12,16],'/owned'),None]),patch.object(runtime.subprocess,'run',side_effect=OSError('failed')):
                with self.assertRaises(OSError):runtime.ensure_venv('/owned/bin/python3.12',target)
            self.assertTrue((target/'old.py').exists())

    def test_server_helper_matches_client_helper(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual((root/'kienzledoku_linux_runtime.py').read_bytes(),(root/'server-windows/linux/kienzledoku_linux_runtime.py').read_bytes())

if __name__=='__main__':unittest.main()

class CudaSetupTests(unittest.TestCase):
    def engine(self):
        import importlib.util
        import sys
        root=Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root/'server-windows/linux'))
        spec=importlib.util.spec_from_file_location('ubuntu182engine',root/'server-windows/linux/install_server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_26_uses_own_repository_and_toolkit_only(self):
        engine=self.engine();calls=[]
        with patch.object(engine,'ubuntu_version',return_value='26.04'),patch.object(engine.Path,'exists',return_value=False),patch.object(engine.pwd,'getpwnam'),patch.object(engine,'run',side_effect=lambda argv,**kwargs:calls.append([str(a) for a in argv])),patch.dict(engine.os.environ,{'WSL_DISTRO_NAME':''}):
            engine.prepare_host()
        self.assertTrue(any('ubuntu2604' in arg for call in calls for arg in call))
        self.assertTrue(any('cuda-toolkit-13-4' in call for call in calls))
        self.assertFalse(any(arg.startswith(('nvidia-driver','cuda-drivers')) for call in calls for arg in call))

    def test_24_and_wsl_keep_previous_repository_and_toolkit(self):
        engine=self.engine()
        for wsl,repo in [('', 'ubuntu2404'),('kienzledoku-server','wsl-ubuntu')]:
            calls=[]
            with patch.object(engine,'ubuntu_version',return_value='24.04'),patch.object(engine.Path,'exists',return_value=False),patch.object(engine.pwd,'getpwnam'),patch.object(engine,'run',side_effect=lambda argv,**kwargs:calls.append([str(a) for a in argv])),patch.dict(engine.os.environ,{'WSL_DISTRO_NAME':wsl}):
                engine.prepare_host()
            self.assertTrue(any(repo in arg for call in calls for arg in call))
            self.assertTrue(any('cuda-toolkit-13-0' in call for call in calls))
