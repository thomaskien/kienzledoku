import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'linux'))
import install_server
import service_migration
from test_gemma_models import configuration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.systemd=self.root/'systemd';self.tmpfiles=self.root/'tmpfiles'
        self.state=self.root/'state';self.state.mkdir();self.tmpfiles.mkdir()
        self.paths=[]
        for role,suffix in (('asr-backend',''),('diarization','-diar')):
            path=self.systemd/('kienzlefon-ai-'+role+'.service.d')/'90-kienzledoku-commander.conf'
            path.parent.mkdir(parents=True)
            text='# kienzledoku-commander\n[Service]\nEnvironment=PYTHONPATH=/opt/kienzledoku-commander\nEnvironment=KIENZLEDOKU_COMMANDER_CONTROL_DIR=/run/kienzledoku-commander'+suffix+'\n'
            if suffix:text+='Environment=KIENZLEDOKU_COMMANDER_CONTROL_GROUP=thomas\n'
            path.write_text(text);self.paths.append(path)
        path=self.tmpfiles/'kienzledoku-commander.conf'
        path.write_text('d /run/kienzledoku-commander 0700 thomas thomas -\nd /run/kienzledoku-commander-diar 0750 root thomas -\n')
        self.paths.append(path)

    def migrate(self):
        return service_migration.migrate_legacy_commander(self.state,self.systemd,self.tmpfiles)

    def test_recognized_files_are_backed_up_unrelated_override_is_preserved(self):
        other=self.paths[1].with_name('10-kienzlefon-gpu.conf');other.write_text('[Service]\nEnvironment=CUDA_VISIBLE_DEVICES=0\n')
        before={str(p):p.read_bytes() for p in self.paths}
        backup=self.migrate()
        manifest=json.loads((backup/'manifest.json').read_text())
        for path,contents in before.items():
            self.assertFalse(Path(path).exists())
            self.assertEqual(contents,(backup/manifest[path]).read_bytes())
        self.assertEqual(0o700,backup.stat().st_mode & 0o777)
        self.assertTrue(other.exists())
        self.assertIsNone(self.migrate())

    def test_unknown_override_aborts_before_removing_any_file(self):
        self.paths[1].write_text(self.paths[1].read_text()+'ExecStart=/unrelated/program\n')
        with self.assertRaisesRegex(ValueError,'Unbekanntes'):
            self.migrate()
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_unknown_tmpfiles_rule_aborts_before_removing_overrides(self):
        self.paths[2].write_text(self.paths[2].read_text()+'d /run/other 0700 root root -\n')
        with self.assertRaisesRegex(ValueError,'Verzeichnisregel'):
            self.migrate()
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_symlink_is_not_followed(self):
        path=self.paths[0];target=self.root/'unrelated';target.write_text(path.read_text())
        path.unlink();path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Verknüpfte'):
            self.migrate()
        self.assertTrue(path.is_symlink());self.assertTrue(target.exists())

    def test_native_units_can_be_enabled_without_changing_windows_start_policy(self):
        runtime=self.root/'runtime';runtime.mkdir()
        (runtime/'prompt_documentation.txt').write_text('synthetic standard prompt')
        for native in (True,False):
            with self.subTest(native=native):
                cfg=configuration(models=['9b-q4'])
                if native:cfg['NativeBind']='0.0.0.0'
                written={};original_write=install_server.write
                def write(path,value,mode=0o644):
                    if str(path).startswith(str(self.root)):
                        original_write(path,value,mode)
                    else:written[str(path)]=value
                with patch.object(install_server,'ROOT',ROOT), \
                     patch.object(install_server,'STATE',self.state), \
                     patch.object(install_server,'CONFIG',self.root/'config'), \
                     patch.object(install_server,'APP',self.root/'runtime'), \
                     patch.object(install_server,'write',side_effect=write), \
                     patch.object(install_server,'run'), \
                     patch.object(service_migration,'migrate_legacy_commander',return_value=None) as migrate:
                    install_server.configure(cfg,dict(vram_mib=24576))
                self.assertEqual(int(native),migrate.call_count)
                self.assertEqual('synthetic standard prompt',(self.root/'config/prompt_documentation.txt').read_text())
                for name in install_server.UNITS:
                    unit=written['/etc/systemd/system/'+name]
                    self.assertEqual(native,'[Install]\nWantedBy=multi-user.target' in unit)
                    self.assertIn('User=kienzledoku-ai',unit)
                    self.assertIn('KillMode=control-group',unit)


if __name__=='__main__':unittest.main()
