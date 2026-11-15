import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

from installer import update_macos as update
from kienzledoku_update import Lease

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'home';self.support=self.root/'support'
        self.current=self.support/'versions/1.6-deadbeef';self.old=self.support/'versions/1.5-1234abcd'
        for path in (self.current,self.old):path.mkdir(parents=True);update.mark_version(path)
        for role,bundle in update.APP_IDS.items():
            contents=self.home/'Applications'/('kienzledoku '+role+'.app')/'Contents';contents.mkdir(parents=True)
            (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle,'KienzledokuRoot':str(self.current),
                'CFBundleShortVersionString':'1.6','KienzledokuPython':str(self.current/'venv/bin/python')}))
        self.runner=mock.Mock(return_value=subprocess.CompletedProcess([],0,'',''))
    def complete(self,**kw):return update.complete_update(self.support,self.home,self.current,reader=lambda:[],runner=self.runner,**kw)
    def test_success_removes_old_code_and_backup_apps_preserves_models_and_configs(self):
        model=self.support/'models/model.gguf';model.parent.mkdir();model.write_bytes(b'model')
        config=self.support/'config.toml';config.write_text('synthetic settings')
        backup=self.current/'kienzledoku connect-previous.app/Contents';backup.mkdir(parents=True)
        (backup/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'de.kienzledoku.connect'}))
        self.assertEqual(1,self.complete())
        self.assertEqual([self.current],list(self.current.parent.iterdir()))
        self.assertFalse(backup.exists());self.assertEqual(b'model',model.read_bytes())
        self.assertEqual('synthetic settings',config.read_text());self.runner.assert_called_once()
    def test_unknown_version_and_symlink_never_deleted(self):
        foreign=self.current.parent/'unrelated';foreign.mkdir()
        with self.assertRaises(ValueError):self.complete()
        self.assertTrue(self.old.exists());self.assertTrue(foreign.exists())
        foreign.rmdir();link=self.current.parent/'1.4.4-deadcafe';link.symlink_to(self.root)
        with self.assertRaises(ValueError):self.complete()
        self.assertTrue(self.old.exists())

    def test_unregistered_backup_does_not_block_cleanup(self):
        app=self.current/'kienzledoku connect-previous.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'de.kienzledoku.connect'}))
        self.runner.return_value=subprocess.CompletedProcess([],1,'','failed to scan '+str(app)+': -10814\n from spotlight\n')
        self.assertEqual(1,self.complete())
        self.assertFalse(app.exists());self.assertFalse(self.old.exists())

    def test_real_registration_errors_stop_before_removing_files(self):
        app=self.current/'kienzledoku connect-previous.app'
        (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'de.kienzledoku.connect'}))
        for code,error in ((1,'failed to scan '+str(app)+': -10810\n'),
                           (1,'failed to scan '+str(app)+': -10814\nadditional failure\n'),
                           (1,''),(2,'failed to scan '+str(app)+': -10814\n')):
            self.runner.return_value=subprocess.CompletedProcess([],code,'',error)
            with self.subTest(code=code,error=error),self.assertRaisesRegex(RuntimeError,'Neue Programme sind bereits aktiviert'):
                self.complete()
            self.assertTrue(app.exists());self.assertTrue(self.old.exists())

    def test_registration_timeout_has_specific_message(self):
        self.runner.side_effect=subprocess.TimeoutExpired('lsregister',20)
        with self.assertRaisesRegex(RuntimeError,'App-Registrierung konnte nicht geprüft'):
            update.unregister_old_app(self.current/'backup.app',self.runner)
    def test_live_old_process_blocks_cleanup(self):
        row=update.Process(12,1,os.getuid(),'birth',str(self.old/'python'))
        with self.assertRaises(RuntimeError):update.complete_update(self.support,self.home,self.current,reader=lambda:[row])
        self.assertTrue(self.old.exists())
    def test_removal_failure_is_not_success(self):
        with self.assertRaises(OSError):self.complete(remove=mock.Mock(side_effect=OSError('synthetic failure')))
        self.assertTrue(self.current.exists());self.assertTrue(self.old.exists())
    def test_old_flat_client_and_recognized_hotfix_apps_are_removed(self):
        (self.support/'kienzledoku.py').write_text('VERSION = "1.3.3"\n')
        (self.support/'kienzledoku_config.py').write_text('# old config module')
        (self.support/'venv').mkdir();(self.support/'assets').mkdir()
        backup=self.support/'hotfix-backups/local-network-141/kienzledoku connect.app/Contents'
        backup.mkdir(parents=True)
        (backup/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'de.kienzledoku.connect'}))
        experiments=self.support/'read-test-results';experiments.mkdir()
        self.complete()
        for name in ('kienzledoku.py','kienzledoku_config.py','venv','assets','hotfix-backups'):
            self.assertFalse((self.support/name).exists(),name)
        self.assertTrue(experiments.exists(),'User test results are outside the installed application payload')
    def test_wrong_app_version_prevents_completion(self):
        path=self.home/'Applications/kienzledoku record.app/Contents/Info.plist'
        info=plistlib.loads(path.read_bytes());info['CFBundleShortVersionString']='1.4.4'
        path.write_bytes(plistlib.dumps(info))
        with self.assertRaises(ValueError):self.complete()
        self.assertTrue(self.old.exists())
    def test_shared_recording_and_exclusive_update_exclude_each_other(self):
        with Lease(self.support/'update.lock'):
            with self.assertRaises(ValueError):
                with update.update_guard(self.support):pass
        with update.update_guard(self.support):
            with self.assertRaises(RuntimeError):Lease(self.support/'update.lock')
        with Lease(self.support/'update.lock'):pass
    def test_idle_launcher_is_stopped_but_child_is_never_signalled(self):
        command=str(self.home/'Applications/kienzledoku connect.app/Contents/MacOS/kienzledoku')
        row=update.Process(123,1,os.getuid(),'birth',command);rows=[row];sent=[]
        def send(pid,sig):
            sent.append((pid,sig))
            if sig==signal.SIGCONT:rows.clear()
        update.stop_idle_launchers(self.home,reader=lambda:list(rows),send=send,sleep=lambda _:None)
        self.assertEqual([(123,signal.SIGSTOP),(123,signal.SIGTERM),(123,signal.SIGCONT)],sent)
        child=update.Process(124,123,os.getuid(),'birth','synthetic-record')
        with self.assertRaises(ValueError):update.stop_idle_launchers(self.home,reader=lambda:[row,child],send=send)
        self.assertEqual(3,len(sent))
    def test_new_child_after_freeze_resumes_launcher_without_terminating(self):
        row=update.Process(123,1,os.getuid(),'birth',str(self.home/'Applications/kienzledoku connect.app/Contents/MacOS/kienzledoku'))
        child=update.Process(124,123,os.getuid(),'birth','synthetic-record');rows=[row];sent=[]
        def send(pid,sig):
            sent.append(sig)
            if sig==signal.SIGSTOP:rows.append(child)
        with self.assertRaises(ValueError):update.stop_idle_launchers(self.home,reader=lambda:list(rows),send=send)
        self.assertEqual([signal.SIGSTOP,signal.SIGCONT],sent)
    def server_reference(self,root):
        agent=self.home/'Library/LaunchAgents/de.kienzledoku.commander.plist'
        agent.parent.mkdir(parents=True,exist_ok=True)
        agent.write_bytes(plistlib.dumps({'Label':'de.kienzledoku.commander',
            'ProgramArguments':[str(root/'venv/bin/python'),str(root/'installer/service_main.py')],
            'WorkingDirectory':str(root)}))
        (root/'installer').mkdir(exist_ok=True)
        (root/'installer/service_main.py').write_text('# active service')
        return agent

    def test_old_reference_without_explicit_preservation_blocks_cleanup(self):
        path=self.home/'Applications/kienzledoku record.app/Contents/Info.plist'
        data=plistlib.loads(path.read_bytes());data.update(KienzledokuRoot=str(self.old),KienzledokuPython=str(self.old/'venv/bin/python'),CFBundleShortVersionString='1.5');path.write_bytes(plistlib.dumps(data))
        with self.assertRaises(RuntimeError):self.complete()
        self.assertTrue(self.old.exists())

    def test_client_only_update_preserves_server_but_removes_old_client_code(self):
        agent=self.server_reference(self.old);before=agent.read_bytes()
        (self.old/'LICENSE').write_text('MIT License')
        (self.old/'kienzledoku.py').write_text('VERSION="1.5"')
        (self.old/'kienzledoku_speech.py').write_text('# obsolete client')
        (self.old/'kienzledoku_document.py').write_text('# shared contract')
        (self.old/'kienzledoku_commander').mkdir()
        (self.old/'asr-venv').mkdir();(self.old/'diar-venv').mkdir()
        (self.old/'installer/core.py').write_text('# obsolete installer')
        obsolete=self.current.parent/'1.4.4-aaaabbbb';obsolete.mkdir();update.mark_version(obsolete)
        saved=update.preserve_unselected(self.support,self.home,False,True)
        self.assertEqual({'commander':self.old},saved)
        self.assertEqual(1,self.complete(preserved=saved))
        self.assertEqual(before,agent.read_bytes());self.assertFalse(obsolete.exists())
        self.assertFalse((self.old/'kienzledoku.py').exists());self.assertFalse((self.old/'kienzledoku_speech.py').exists())
        self.assertEqual(['service_main.py'],[p.name for p in (self.old/'installer').iterdir()])
        self.assertTrue((self.old/'asr-venv').exists());self.assertTrue((self.old/'diar-venv').exists())
        self.assertTrue((self.old/'kienzledoku_document.py').exists())
        self.assertTrue(update.owned_version(self.old))
        self.assertEqual('MIT License',(self.old/'LICENSE').read_text())
        self.assertEqual(saved,update.preserve_unselected(self.support,self.home,False,True))

    def test_retained_server_imports_in_fresh_process_after_client_pruning(self):
        import shutil
        import subprocess
        import sys
        self.server_reference(self.old)
        source=Path(__file__).resolve().parents[1]
        shutil.copytree(source/'kienzledoku_commander',self.old/'kienzledoku_commander',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('kienzledoku_document.py','kienzledoku_commander_client.py','kienzledoku.py'):
            shutil.copy2(source/name,self.old/name)
        self.complete(preserved={'commander':self.old})
        result=subprocess.run([sys.executable,'-I','-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import kienzledoku_commander.api;import kienzledoku_commander.__main__',str(self.old)],
            cwd=self.old,capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertFalse((self.old/'kienzledoku.py').exists())

    def test_server_only_update_preserves_client_and_removes_old_server_code(self):
        self.server_reference(self.old)
        (self.old/'LICENSE').write_text('MIT License')
        for role in update.APP_IDS:
            path=self.home/'Applications'/('kienzledoku '+role+'.app')/'Contents/Info.plist'
            data=plistlib.loads(path.read_bytes());data.update(KienzledokuRoot=str(self.old),KienzledokuPython=str(self.old/'venv/bin/python'),CFBundleShortVersionString='1.5');path.write_bytes(plistlib.dumps(data))
        for folder in ('asr-venv','diar-venv','llama','kienzledoku_commander'):(self.old/folder).mkdir()
        (self.old/'kienzledoku.py').write_text('VERSION="1.5"')
        saved=update.preserve_unselected(self.support,self.home,True,False)
        self.assertEqual({'record':self.old,'connect':self.old},saved)
        self.server_reference(self.current)
        self.complete(preserved=saved)
        self.assertEqual('MIT License',(self.old/'LICENSE').read_text())
        self.assertTrue((self.old/'kienzledoku.py').exists())
        for folder in ('asr-venv','diar-venv','llama','kienzledoku_commander','installer'):self.assertFalse((self.old/folder).exists())

    def test_active_reference_changed_during_update_is_not_deleted(self):
        self.server_reference(self.old)
        saved=update.preserve_unselected(self.support,self.home,False,True)
        self.server_reference(self.current)
        with self.assertRaises(RuntimeError):self.complete(preserved=saved)
        self.assertTrue(self.old.exists())

    def test_replaced_client_file_still_in_use_blocks_pruning(self):
        self.server_reference(self.old);script=self.old/'kienzledoku.py';script.write_text('# client')
        with self.assertRaises(RuntimeError):
            update.complete_update(self.support,self.home,self.current,
                preserved={'commander':self.old},reader=lambda:[update.Process(123,1,os.getuid(),'birth',str(script))],runner=self.runner)
        self.assertTrue(script.exists())

    def test_unknown_file_in_active_server_is_never_removed(self):
        self.server_reference(self.old);unknown=self.old/'personal';unknown.write_text('# user data')
        with self.assertRaises(ValueError):self.complete(preserved={'commander':self.old})
        self.assertTrue(unknown.exists())

if __name__=='__main__':unittest.main()
