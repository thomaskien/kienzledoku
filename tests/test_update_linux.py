"""Synthetic whole-tree upgrades; no package manager or services are invoked."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from kienzledoku_update import Lease
ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
server=module('managed_update',ROOT/'server-windows/linux/managed_update.py')
client=module('linux_update_client',ROOT/'linux/update_client.py')

class LinuxUpdateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=str(Path(tempfile.gettempdir()).resolve()));self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'serial_server.py').write_text('# new')
        self.base=self.root/'installed';self.target=self.base/'runtime'
    def test_fresh_install_then_upgrade_removes_obsolete_code_but_not_models(self):
        server.replace_tree(self.source,self.target,'serial_server.py')
        server.finalize(self.base)
        (self.target/'obsolete.py').write_text('# old')
        models=self.base/'models';models.mkdir();(models/'large.gguf').write_bytes(b'preserved')
        server.replace_tree(self.source,self.target,'serial_server.py')
        self.assertFalse((self.target/'obsolete.py').exists())
        self.assertTrue((self.base/'.update-backups').exists())
        server.finalize(self.base)
        self.assertFalse((self.base/'.update-backups').exists())
        self.assertEqual(b'preserved',(models/'large.gguf').read_bytes())
    def test_changed_or_extra_active_file_prevents_false_success(self):
        server.replace_tree(self.source,self.target,'serial_server.py')
        (self.target/'unexpected.py').write_text('# stale')
        with self.assertRaises(ValueError):server.finalize(self.base)
        self.assertTrue((self.base/'.update-backups').exists())
    def test_copy_failure_keeps_old_tree_and_unknown_directory_is_rejected(self):
        self.target.mkdir(parents=True);(self.target/'serial_server.py').write_text('# old')
        with mock.patch.object(server.shutil,'copytree',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):server.replace_tree(self.source,self.target,'serial_server.py')
        self.assertEqual('# old',(self.target/'serial_server.py').read_text())
        (self.target/'serial_server.py').unlink()
        with self.assertRaises(ValueError):server.replace_tree(self.source,self.target,'serial_server.py')
    def test_symlink_source_and_parent_are_rejected(self):
        (self.source/'link').symlink_to(self.root)
        with self.assertRaises(ValueError):server.replace_tree(self.source,self.target,'serial_server.py')
        (self.source/'link').unlink();self.base.symlink_to(self.source)
        with self.assertRaises(ValueError):server.replace_tree(self.source,self.target,'serial_server.py')
    def test_failed_promotion_and_restore_preserve_previous_tree(self):
        self.target.mkdir(parents=True);(self.target/'serial_server.py').write_text('# old')
        original=Path.rename
        def rename(path,destination):
            if path.name in ('candidate','previous'):
                raise OSError('synthetic rename failure')
            return original(path,destination)
        with mock.patch.object(Path,'rename',rename),self.assertRaises(OSError):
            server.replace_tree(self.source,self.target,'serial_server.py')
        saved=list((self.base/'.update-backups').glob('*/previous/serial_server.py'))
        self.assertEqual(1,len(saved));self.assertEqual('# old',saved[0].read_text())
        self.assertFalse(self.target.exists())
    def test_linux_client_fresh_payload_replaces_venvs_and_preserves_config(self):
        data=self.root/'client';data.mkdir();(data/'kienzledoku.py').write_text('# old')
        (data/'obsolete.py').write_text('# obsolete');(data/'venvs').mkdir()
        config=self.root/'config';config.mkdir();(config/'config.toml').write_text('# saved')
        def run(*args,**kw):
            self.assertFalse(data.exists())
            with self.assertRaises(RuntimeError):Lease(config/'update.lock')
            data.mkdir();(data/'kienzledoku.py').write_text('# new')
        client.install(data,config,['synthetic'],runner=run,closed=lambda _:None)
        self.assertEqual(['kienzledoku.py'],[p.name for p in data.iterdir()])
        self.assertEqual('# saved',(config/'config.toml').read_text())
        self.assertEqual([],list(data.parent.glob('.kienzledoku-client-update-*')))
    def test_failed_client_rebuild_restores_previous_files(self):
        data=self.root/'client';data.mkdir();(data/'kienzledoku.py').write_text('# old')
        def run(*args,**kw):
            data.mkdir();(data/'partial').write_text('# broken');raise RuntimeError('synthetic')
        with self.assertRaises(RuntimeError):client.install(data,self.root/'config',['synthetic'],runner=run,closed=lambda _:None)
        self.assertEqual('# old',(data/'kienzledoku.py').read_text());self.assertFalse((data/'partial').exists())
    def test_active_recording_blocks_before_client_files_move(self):
        data=self.root/'client';data.mkdir();(data/'kienzledoku.py').write_text('# old')
        config=self.root/'config'
        with Lease(config/'update.lock'):
            with self.assertRaises(RuntimeError):client.install(data,config,['synthetic'],runner=mock.Mock(),closed=lambda _:None)
        self.assertEqual('# old',(data/'kienzledoku.py').read_text())

    def test_native_server_cleanup_failure_cannot_be_reported_as_ready(self):
        import io
        import os
        import sys
        sys.path.insert(0,str(ROOT/'server-windows/linux'))
        self.addCleanup(sys.path.remove,str(ROOT/'server-windows/linux'))
        control=module('update_control_test',ROOT/'server-windows/linux/control.py')
        state=self.root/'state';state.mkdir();config=self.root/'config';config.mkdir()
        (state/'windows-config.json').write_text('{"GpuIndex":0}')
        (state/'llama-build.json').write_text('{"compute_capability":"8.6"}')
        (config/'token.env').write_text('KIENZLEDOKU_COMMANDER_TOKEN=\n')
        ready={'asr_ready':True,'transition_running':False,'last_error':None,'phase':'asr_ready'}
        response=io.BytesIO(json.dumps(ready).encode())
        with mock.patch.object(control.os,'geteuid',return_value=0), \
             mock.patch.dict(os.environ,{},clear=True), \
             mock.patch.object(control,'STATE',state),mock.patch.object(control,'CONFIG',config), \
             mock.patch.object(control,'hardware',return_value={'compute_capability':'8.6','vram_mib':24576}), \
             mock.patch.object(control,'validate_config'),mock.patch.object(control,'check_memory'), \
             mock.patch.object(control.subprocess,'run'),mock.patch.object(control,'start_unit'), \
             mock.patch.object(control.urllib.request,'build_opener') as opener, \
             mock.patch.dict(sys.modules,{'managed_update':server}), \
             mock.patch.object(server,'finalize',side_effect=ValueError('synthetic incomplete cleanup')), \
             mock.patch('builtins.print') as output:
            opener.return_value.open.return_value=response
            with self.assertRaisesRegex(ValueError,'incomplete cleanup'):control.execute('start')
            output.assert_not_called()

if __name__=='__main__':unittest.main()
