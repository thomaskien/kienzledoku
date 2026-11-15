import copy
import hashlib
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from installer import core, wizard
from kienzledoku_http import configure_server

HW=dict(platform='darwin',arch='arm64',ram_gib=32,free_gib=100,server_supported=True)

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        isolated_hf = mock.patch.dict(os.environ, {
            'HF_TOKEN':'', 'HUGGING_FACE_HUB_TOKEN':'', 'HF_TOKEN_PATH':'',
            'HF_HOME':str(self.root/'hf'), 'XDG_CACHE_HOME':str(self.root/'cache')})
        isolated_hf.start(); self.addCleanup(isolated_hf.stop)
        self.cfg=core.defaults(HW,self.root)
    def tearDown(self): self.temp.cleanup()
    def test_default_models_and_privacy_options(self):
        self.assertEqual('http://10.0.83.140:8185',self.cfg['commander_url'])
        self.assertEqual(self.cfg['quality_models'],{'basis':'qwen4-q4','gruendlich':'gemma12-q8','sehr_gruendlich':'27b-q4'})
        self.assertFalse(self.cfg['auth_enabled']); self.assertTrue(self.cfg['asr_on_demand'])
        self.assertEqual(self.cfg['memory_mode'],'serial')
        core.validate(self.cfg,HW)
    def test_existing_installer_version_is_never_overwritten(self):
        from installer import build_macos
        artifact=self.root/('kienzledoku-'+core.VERSION+'-macOS-arm64.dmg')
        artifact.write_bytes(b'already delivered artifact')
        with mock.patch.object(build_macos,'run') as run:
            with self.assertRaisesRegex(FileExistsError,'Versionsnummer erhöhen'):
                build_macos.build('arm64',self.root,self.root/'cache')
        run.assert_not_called()
        self.assertEqual(b'already delivered artifact',artifact.read_bytes())
    def test_huggingface_token_is_prefilled_from_environment_and_private_storage(self):
        (self.root/'hf').mkdir()
        (self.root/'hf/token').write_text('hf_synthetic_login\n')
        self.assertEqual(core.defaults(HW,self.root)['hf_token'],'hf_synthetic_login')
        core.atomic_write(self.root/'huggingface.token','hf_synthetic_installer')
        self.assertEqual(core.bootstrap(HW,self.root)['defaults']['hf_token'],'hf_synthetic_installer')
        with mock.patch.dict(os.environ,{'HF_TOKEN':'hf_synthetic_env'}):
            self.assertEqual(core.defaults(HW,self.root)['hf_token'],'hf_synthetic_env')
        # Invalid/oversized saved contents must not become a partial credential.
        (self.root/'huggingface.token').write_text('bad\nmultiple\nvalues')
        self.assertEqual(core.huggingface_token(self.root),'hf_synthetic_login')
        (self.root/'huggingface.token').write_text('x'*4096+'\nrest')
        self.assertEqual(core.huggingface_token(self.root),'hf_synthetic_login')
    def test_huggingface_explicit_token_path_and_xdg_cache(self):
        token_file=self.root/'custom-token';token_file.write_text('hf_synthetic_custom')
        with mock.patch.dict(os.environ,{'HF_TOKEN_PATH':str(token_file)}):
            self.assertEqual(core.huggingface_token(self.root),'hf_synthetic_custom')
        cache_token=self.root/'cache/huggingface/token'
        cache_token.parent.mkdir(parents=True);cache_token.write_text('hf_synthetic_xdg')
        with mock.patch.dict(os.environ,{'HF_HOME':''}):
            self.assertEqual(core.huggingface_token(self.root),'hf_synthetic_xdg')
    def test_multiple_models_grade_assignment_and_memory(self):
        self.cfg['selected_models']+=['9b-q6']
        self.cfg['quality_models']['gruendlich']='9b-q6'; core.validate(self.cfg,HW)
        self.cfg['quality_models']['basis']='gemma12-q8'
        with self.assertRaises(ValueError):core.validate(self.cfg,HW)
        self.cfg['quality_models']['basis']='qwen4-q4'
        with self.assertRaises(ValueError):core.validate(self.cfg,dict(HW,ram_gib=16))
    def test_config_never_serializes_credentials(self):
        self.cfg['server_token']='synthetic-server-token'; self.cfg['remote_llm_token']='synthetic-remote-token'
        text=core.commander_toml(self.cfg,self.root/'version',self.root)
        self.assertNotIn('synthetic-',text)
        import tomllib
        cfg=tomllib.loads(text)
        self.assertFalse(cfg['server']['auth_enabled']);self.assertTrue(cfg['policy']['asr_on_demand'])
        self.assertEqual(cfg['models']['basis']['model_id'],'qwen4-q4')
        self.assertEqual(cfg['backends']['platform'],'macos')
    def test_remote_and_client_do_not_require_local_models(self):
        self.cfg.update(mode='client',selected_models=[],quality_models={})
        core.validate(self.cfg,dict(HW,server_supported=False,arch='x86_64'))
        self.cfg.update(mode='combined',remote_llm_url='http://192.0.2.5:8185')
        core.validate(self.cfg,HW);self.assertEqual(core.plan(self.cfg,HW)['download_bytes'],0)
        self.cfg['remote_llm_url']='http://user:password@example.org:8185'
        with self.assertRaises(ValueError):core.validate(self.cfg,HW)
    def test_secret_and_field_validation(self):
        for field,value in [('hf_token','bad\ntoken'),('fields',['anamnese','bad']),('fields',['befund','anamnese']),('fields',[])]:
            cfg=copy.deepcopy(self.cfg);cfg[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):core.validate(cfg,HW)
    def test_active_patient_window_blocks_update(self):
        import fcntl
        lock=self.root/'sessions/desktop/record.lock';lock.parent.mkdir(parents=True)
        with lock.open('w') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'Patientenfenster'):
                core.require_closed_record(self.root)
        core.require_closed_record(self.root)
    def test_generated_server_roles_load_without_fake_llm_profiles(self):
        from kienzledoku_commander.config import load_settings
        for role,remote in [('full',''),('asr',''),('llm',''),('asr','http://192.0.2.5:8185')]:
            cfg=copy.deepcopy(self.cfg);cfg.update(server_role=role,remote_llm_url=remote)
            with mock.patch.object(core,'hardware',return_value=HW):
                path=self.root/'candidate.toml';path.write_text(core.commander_toml(cfg,self.root/'version',self.root))
            settings=load_settings(path)
            if role=='asr' or remote:self.assertEqual((),settings.allowed)
            else:self.assertEqual(('basis','gruendlich','sehr_gruendlich'),settings.allowed)
            self.assertEqual('serial',settings.memory_mode)

    def test_failed_activation_restores_settings_and_new_apps(self):
        import kienzledoku_config as record
        support=self.root/'support';support.mkdir();version=self.root/'version';version.mkdir()
        home=self.root/'home';home.mkdir();(home/'Applications').mkdir()
        config=record.defaults();record.save(config,support/'config.toml')
        original=(support/'config.toml').read_bytes()
        installer=core.Installer(support,HW)
        destinations=[]
        def stage(_version,_runtime,mode):
            app=version/(mode+'.app');app.mkdir()
            destination=home/'Applications'/app.name;destinations.append(destination)
            return app,destination
        def run(argv,**_):
            if 'lsregister' in str(argv[0]):raise RuntimeError('Synthetischer Aktivierungsfehler')
        cfg=copy.deepcopy(self.cfg);cfg['mode']='client'
        with mock.patch.object(Path,'home',return_value=home), \
             mock.patch.object(installer,'_app',side_effect=stage), \
             mock.patch.object(installer,'run',side_effect=run):
            with self.assertRaisesRegex(RuntimeError,'Synthetischer'):
                installer._activate(cfg,version,Path(sys.executable),False,True)
        self.assertEqual(original,(support/'config.toml').read_bytes())
        self.assertTrue(all(not p.exists() for p in destinations))
        self.assertFalse((support/'commander.token').exists())

    def test_client_install_copies_and_publishes_both_native_launchers(self):
        payload=self.root/'package/payload';payload.mkdir(parents=True)
        for name in ('kienzledoku_commander','local-ai-macos','assets','installer'):
            (payload/name).mkdir()
        launchers={'record':b'synthetic record launcher','connect':b'synthetic connect launcher'}
        for mode,content in launchers.items():
            (payload/f'kienzledoku_{mode}_app').write_bytes(content)
        for name in ('kienzledoku_window','kienzleconnect','requirements-asr-client.txt','prompt_documentation.txt','assets/kienzledoku-record.icns'):
            (payload/name).write_bytes(b'synthetic payload')
        (payload.parent/'runtime/python/bin').mkdir(parents=True)
        (payload.parent/'runtime/python/bin/python3.12').write_bytes(b'synthetic runtime')
        home=self.root/'home';home.mkdir()
        support=self.root/'support'
        # A completed earlier session leaves its lock file behind. The updater
        # holds this lock throughout activation and must not lock it a second time.
        record_lock=support/'sessions/desktop/record.lock'
        record_lock.parent.mkdir(parents=True);record_lock.touch()
        installer=core.Installer(support,HW)
        cfg=copy.deepcopy(self.cfg);cfg['mode']='client'
        with mock.patch.object(core,'ROOT',payload), \
             mock.patch.object(Path,'home',return_value=home), \
             mock.patch.object(core.shutil,'disk_usage',return_value=mock.Mock(free=100*2**30)), \
             mock.patch.object(installer,'run'):
            installer._work(cfg)
        state=installer.snapshot()
        self.assertTrue(state['done'],state['error'])
        self.assertTrue(state['client_installed'])
        for mode,content in launchers.items():
            app=home/'Applications'/f'kienzledoku {mode}.app'
            self.assertEqual(content,(app/'Contents/MacOS/kienzledoku').read_bytes())
        self.assertEqual(1,len(list((support/'versions').iterdir())))

    def test_client_only_update_with_existing_server_preserves_server_and_removes_old_clients(self):
        import plistlib
        from installer import update_macos
        payload=self.root/'partial-package/payload';payload.mkdir(parents=True)
        for name in ('kienzledoku_commander','local-ai-macos','assets','installer'):(payload/name).mkdir()
        for name in ('kienzledoku_window','kienzleconnect','kienzledoku_record_app','kienzledoku_connect_app',
                     'requirements-asr-client.txt','prompt_documentation.txt','assets/kienzledoku-record.icns'):
            (payload/name).write_bytes(b'synthetic payload')
        (payload.parent/'runtime/python/bin').mkdir(parents=True)
        (payload.parent/'runtime/python/bin/python3.12').write_bytes(b'synthetic runtime')
        home=self.root/'partial-home';home.mkdir();support=self.root/'partial-support'
        previous=support/'versions/1.5-deadbeef';previous.mkdir(parents=True);update_macos.mark_version(previous)
        (previous/'installer').mkdir();(previous/'installer/service_main.py').write_text('# server unchanged')
        (previous/'kienzledoku.py').write_text('VERSION="1.5"')
        (previous/'kienzledoku_document.py').write_text('# shared server contract')
        agent=home/'Library/LaunchAgents/de.kienzledoku.commander.plist';agent.parent.mkdir(parents=True)
        agent.write_bytes(plistlib.dumps({'Label':'de.kienzledoku.commander',
            'ProgramArguments':[str(previous/'venv/bin/python'),str(previous/'installer/service_main.py')],
            'WorkingDirectory':str(previous)}));saved_agent=agent.read_bytes()
        (support/'commander').mkdir();settings=support/'commander/config.toml';settings.write_text('# unchanged live server')
        installer=core.Installer(support,HW);cfg=copy.deepcopy(self.cfg);cfg['mode']='client'
        with mock.patch.object(core,'ROOT',payload),mock.patch.object(Path,'home',return_value=home), \
             mock.patch.object(core.shutil,'disk_usage',return_value=mock.Mock(free=100*2**30)), \
             mock.patch.object(installer,'run') as run,mock.patch.object(installer,'_stop_commander') as stop, \
             mock.patch.object(core,'download',side_effect=AssertionError('No server/model download during client update')):
            installer._work(cfg)
        self.assertTrue(installer.snapshot()['done'],installer.snapshot()['error'])
        stop.assert_not_called();self.assertFalse(any('launchctl' in str(call) for call in run.call_args_list))
        self.assertEqual(saved_agent,agent.read_bytes());self.assertEqual('# unchanged live server',settings.read_text())
        self.assertEqual('# server unchanged',(previous/'installer/service_main.py').read_text())
        self.assertFalse((previous/'kienzledoku.py').exists())
        self.assertEqual(2,len(list((support/'versions').iterdir())))
        for mode in ('record','connect'):
            info=plistlib.loads((home/'Applications'/('kienzledoku '+mode+'.app')/'Contents/Info.plist').read_bytes())
            self.assertEqual(core.VERSION,info['CFBundleShortVersionString'])
            self.assertNotEqual(str(previous),info['KienzledokuRoot'])

    def test_missing_client_launcher_fails_before_runtime_or_model_setup(self):
        payload=self.root/'payload';payload.mkdir()
        for name in ('kienzledoku_window','kienzleconnect','kienzledoku_record_app'):
            (payload/name).write_bytes(b'synthetic payload')
        installer=core.Installer(self.root/'support',HW)
        cfg=copy.deepcopy(self.cfg);cfg['mode']='combined'
        with mock.patch.object(core,'ROOT',payload), \
             mock.patch.object(Path,'home',return_value=self.root/'synthetic-home'), \
             mock.patch.object(installer,'run') as run, \
             mock.patch.object(core,'download') as download:
            installer._work(cfg)
        state=installer.snapshot()
        self.assertFalse(state['done'])
        self.assertIn('Installationspaket unvollständig',state['error'])
        self.assertIn('kienzledoku_connect_app',state['error'])
        run.assert_not_called();download.assert_not_called()

    def test_server_activation_creates_private_control_directory(self):
        from kienzledoku_commander.ownership import owner
        support=self.root/'support';support.mkdir();version=self.root/'version';version.mkdir()
        home=self.root/'home';home.mkdir()
        installer=core.Installer(support,HW)
        response=mock.MagicMock();response.__enter__.return_value.status=200
        cfg=copy.deepcopy(self.cfg);cfg['mode']='server';cfg['hf_token']='hf_synthetic_saved'
        with mock.patch.object(Path,'home',return_value=home), \
             mock.patch.object(installer,'run'), \
             mock.patch.object(installer,'_wait_commander'), \
             mock.patch.object(core.subprocess,'run'), \
             mock.patch.object(core,'urlopen',return_value=response):
            installer._activate(cfg,version,Path(sys.executable),True,False)
        control=support/'commander/run'
        self.assertEqual(0o700,control.stat().st_mode&0o777)
        with owner(control):pass
        self.assertEqual(0o600,(support/'huggingface.token').stat().st_mode&0o777)
        self.assertEqual(core.defaults(HW,support)['hf_token'],'hf_synthetic_saved')
        for path in ('installer.json','commander/credentials.json','commander/config.toml'):
            self.assertNotIn('hf_synthetic_saved',(support/path).read_text())
        self.assertNotIn('hf_synthetic_saved',json.dumps(installer.snapshot()))

    def test_private_atomic_config(self):
        path=self.root/'private/settings'
        core.atomic_write(path,'hello');self.assertEqual(path.stat().st_mode&0o777,0o600)
        core.atomic_write(path,'next');self.assertEqual(path.read_text(),'next')
    def test_archive_traversal_is_refused(self):
        archive=self.root/'bad.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            member=tarfile.TarInfo('../outside');member.size=3;tar.addfile(member,io.BytesIO(b'bad'))
        with self.assertRaises(tarfile.FilterError):core.extract_archive(archive,self.root/'extract')
        self.assertFalse((self.root/'outside').exists())
    def test_download_checks_hash_before_publication(self):
        content=b'synthetic artifact'
        class Source(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        server=ThreadingHTTPServer(('127.0.0.1',0),Source)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:%s/model'%server.server_address[1]; dest=self.root/'model'
            with self.assertRaises(ValueError):core.download(url,dest,'0'*64)
            self.assertFalse(dest.exists());self.assertFalse(dest.with_name('model.part').exists())
            core.download(url,dest,hashlib.sha256(content).hexdigest());self.assertEqual(dest.read_bytes(),content)
        finally:server.shutdown();server.server_close();thread.join()
    def test_installer_http_auth_csrf_and_no_mutation_from_read(self):
        installer=core.Installer(self.root,HW);server=ThreadingHTTPServer(('127.0.0.1',0),wizard.handler(installer,'synthetic-csrf'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=configure_server(server)
        origin=url.split('/open')[0];opener=build_opener(HTTPCookieProcessor(CookieJar()))
        try:
            with self.assertRaises(HTTPError) as denied:opener.open(origin+'/api/bootstrap')
            self.assertEqual(denied.exception.code,403)
            opener.open(url).close()
            data=json.load(opener.open(origin+'/api/bootstrap'));self.assertEqual(data['csrf'],'synthetic-csrf')
            self.assertFalse((self.root/'installer.json').exists())
            body=json.dumps(self.cfg).encode()
            with self.assertRaises(HTTPError):opener.open(Request(origin+'/api/install',body,{'Content-Type':'application/json'}))
            headers={'Content-Type':'application/json','X-CSRF-Token':'synthetic-csrf','Origin':origin}
            result=json.load(opener.open(Request(origin+'/api/validate',body,headers)))
            self.assertGreater(result['download_bytes'],0)
            self.assertFalse(installer.snapshot()['running'])
            headers['Origin']='https://unrelated.example'
            with self.assertRaises(HTTPError):opener.open(Request(origin+'/api/token',b'{}',headers))
        finally:server.shutdown();server.server_close();thread.join()
    def test_cancel_stops_only_own_child(self):
        installer=core.Installer(self.root,HW)
        outcome=[]
        def work():
            try:installer.run([sys.executable,'-c','import time; time.sleep(60)'])
            except InterruptedError:outcome.append('cancelled')
        t=threading.Thread(target=work);t.start()
        deadline=time.monotonic()+5
        while installer.proc is None and time.monotonic()<deadline:time.sleep(.01)
        installer.cancel.set();t.join(15)
        self.assertFalse(t.is_alive());self.assertEqual(outcome,['cancelled']);self.assertIsNone(installer.proc)

if __name__=='__main__':unittest.main()
