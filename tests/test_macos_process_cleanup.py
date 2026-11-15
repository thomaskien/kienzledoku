from dataclasses import replace
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from kienzledoku_commander import macos_processes as cleanup
from kienzledoku_commander.ownership import owner


class CleanupTests(unittest.TestCase):
    support = Path('/synthetic/home/Library/Application Support/Kienzledoku')

    def process(self, role='diar'):
        root = self.support / 'versions/1.5-deadbeef'
        executable = str(root / (role+'-venv/bin/python'))
        script = 'diarization_server_mps.py' if role == 'diar' else 'asr_server_mlx.py'
        return cleanup.Process(123456, 1, os.getuid(), 'Thu Nov 12 18:00:00 2026',
                               executable, executable+' '+str(root/'local-ai-macos'/script))

    def test_only_orphaned_owned_model_commands_are_selected(self):
        p = self.process()
        self.assertEqual('diar', cleanup._role(p, self.support))
        self.assertEqual('asr', cleanup._role(self.process('asr'), self.support))
        for changed in (replace(p, ppid=777), replace(p, uid=p.uid+1),
                        replace(p, command=p.executable+' /tmp/unrelated.py'),
                        replace(p, executable='/usr/bin/python3'),
                        replace(p, command=p.command+' --unexpected'),
                        replace(p, executable=str(self.support/'versions/invalid/diar-venv/bin/python'))):
            self.assertIsNone(cleanup._role(changed, self.support))

    def test_llama_requires_owned_model_root_and_commander_signature(self):
        exe=str(self.support/'versions/1.4.4-deadbeef/llama/llama-server')
        args=exe+' --model '+str(self.support/'models/synthetic/model.gguf')+' --alias basis --host 127.0.0.1 --port 8086 --parallel 1 --log-disable'
        p=cleanup.Process(123456,1,os.getuid(),'synthetic birth',exe,args)
        self.assertEqual('llm',cleanup._role(p,self.support))
        self.assertIsNone(cleanup._role(replace(p,command=exe+' --model /tmp/foreign.gguf'),self.support))
        self.assertIsNone(cleanup._role(replace(p,ppid=987),self.support))

    def test_reused_pid_is_not_signalled(self):
        p=self.process()
        with mock.patch.object(cleanup,'_read_process',return_value=replace(p,started='different birth')), \
             mock.patch.object(cleanup.os,'kill') as kill:
            self.assertFalse(cleanup._terminate(p,self.support))
        kill.assert_not_called()

    def test_pid_reuse_after_term_never_receives_kill(self):
        p=self.process()
        with mock.patch.object(cleanup,'_read_process',side_effect=[p,replace(p,started='different birth')]), \
             mock.patch.object(cleanup.os,'kill') as kill:
            self.assertTrue(cleanup._terminate(p,self.support))
        kill.assert_called_once_with(p.pid,signal.SIGTERM)

    def test_stubborn_exact_same_orphan_is_killed_after_grace(self):
        p=self.process()
        with mock.patch.object(cleanup,'_read_process',side_effect=[p,p,None]), \
             mock.patch.object(cleanup.os,'kill') as kill:
            self.assertTrue(cleanup._terminate(p,self.support,grace=0))
        self.assertEqual([mock.call(p.pid,signal.SIGTERM),mock.call(p.pid,signal.SIGKILL)],kill.call_args_list)

    def test_custom_installation_is_not_scanned(self):
        with mock.patch.object(cleanup.sys,'platform','darwin'),mock.patch.object(cleanup,'_candidates') as scan:
            self.assertEqual([],cleanup.cleanup_orphans('/tmp/unrelated/run'))
        scan.assert_not_called()

    def test_existing_owner_prevents_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            control=Path(directory)/'run';control.mkdir(mode=0o700)
            with owner(control),mock.patch.object(cleanup,'cleanup_orphans') as clean:
                with self.assertRaisesRegex(RuntimeError,'nicht vollständig beendet'):
                    cleanup.cleanup_after_stop(control,timeout=0)
                clean.assert_not_called()
            with mock.patch.object(cleanup,'cleanup_orphans',return_value=['diar']) as clean:
                self.assertEqual(['diar'],cleanup.cleanup_after_stop(control))
                clean.assert_called_once_with(control)

    @unittest.skipUnless(sys.platform=='darwin','Real Mac process metadata')
    def test_real_orphan_is_cleaned_while_live_child_and_foreign_script_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory).resolve();support=home/'Library/Application Support/Kienzledoku'
            root=support/'versions/1.4.4-deadbeef'
            executable=root/'diar-venv/bin/python';executable.parent.mkdir(parents=True)
            # Homebrew Python re-execs its framework binary and changes argv[0].
            # This tiny sleeper represents the installed standalone executable.
            fixture=home/'sleeper.c';fixture.write_text('#include <unistd.h>\nint main(void){sleep(60);return 0;}\n')
            subprocess.run(['/usr/bin/clang',str(fixture),'-o',str(executable)],check=True,capture_output=True)
            script=root/'local-ai-macos/diarization_server_mps.py';script.parent.mkdir()
            script.write_text('import time\ntime.sleep(60)\n')
            foreign=script.with_name('unrelated.py');foreign.write_text(script.read_text())
            control=support/'commander/run';control.mkdir(parents=True,mode=0o700)
            parent='import subprocess,sys; p=subprocess.Popen(sys.argv[1:],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); print(p.pid)'
            orphan=int(subprocess.check_output([sys.executable,'-c',parent,str(executable),str(script)],text=True))
            live=subprocess.Popen([executable,script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            unrelated=subprocess.Popen([executable,foreign],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    p=cleanup._read_process(orphan)
                    if p and p.ppid==1:break
                    time.sleep(.02)
                self.assertEqual('diar',cleanup._role(p,support),repr(p))
                with mock.patch.object(Path,'home',return_value=home),owner(control):
                    self.assertEqual(['diar'],cleanup.cleanup_orphans(control))
                self.assertIsNone(cleanup._read_process(orphan))
                self.assertIsNone(live.poll());self.assertIsNone(unrelated.poll())
            finally:
                for proc in (live,unrelated):proc.terminate();proc.wait(timeout=3)
                remaining=cleanup._read_process(orphan)
                if remaining and remaining==p:os.kill(orphan,signal.SIGKILL)


if __name__=='__main__':unittest.main()
