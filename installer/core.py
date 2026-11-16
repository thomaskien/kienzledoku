"""Shared installation plan and macOS installation engine. No patient data."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kienzledoku_document import DEFAULT_DOCUMENT_FIELDS, DOCUMENT_FIELDS, DOCUMENT_LABELS, validate_fields
from kienzledoku_product_key import production_build
from kienzledoku_config import DEFAULT_COMMANDER_URL

VERSION = '1.8'
GRADES = ('basis', 'gruendlich', 'sehr_gruendlich')
GRADE_LABELS = dict(zip(GRADES, ('Basis', 'Gründlich', 'Sehr gründlich')))
DIARIZATION_MODES = {'resident':'Immer geladen', 'with_asr':'Zusammen mit Whisper', 'serial':'Seriell'}
DOCS_URL = 'https://github.com/thomaskien/kienzledoku/blob/main/README.md#t2med-einrichten-und-verwenden'
CATALOG = json.loads((ROOT / 'installer/models.json').read_text())
LOCKS = json.loads((ROOT / 'installer/runtime-lock.json').read_text())
WHISPER_REV = '49e6aa286ad60c14352c404340ded53710378a11'
WHISPER_FILES = {'weights.npz': '05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d', 'config.json': '34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3'}
PYANNOTE_REPO = 'pyannote/speaker-diarization-community-1'
PYANNOTE_REV = '3533c8cf8e369892e6b79ff1bf80f7b0286a54ee'
SECRET_FIELDS = ('commander_token', 'server_token', 'remote_llm_token', 'hf_token')


def support_dir():
    return Path.home() / 'Library/Application Support/Kienzledoku'


def hardware():
    ram = 0
    try:
        ram = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], stderr=subprocess.DEVNULL, timeout=5)) // 2**30
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    addresses=[]
    for interface in ('en0','en1','en2','en3','en4','en5'):
        try:
            ip=subprocess.check_output(['/usr/sbin/ipconfig','getifaddr',interface],stderr=subprocess.DEVNULL,timeout=2,text=True).strip()
            if ip and ip not in addresses: addresses.append(ip)
        except (OSError,subprocess.SubprocessError): pass
    return dict(platform=sys.platform, arch=platform.machine(), ram_gib=ram,lan_addresses=addresses,
                free_gib=shutil.disk_usage(Path.home()).free // 2**30,
                server_supported=sys.platform == 'darwin' and platform.machine() == 'arm64' and ram >= 16)


def huggingface_token(support):
    """Reuse a configured token without importing HF or making network calls."""
    def clean(value):
        value = value.strip()
        return value if len(value) <= 4096 and not any(c.isspace() for c in value) else ''
    for name in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        token = clean(os.environ.get(name, ''))
        if token:
            return token
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')
    hf_home = Path(os.environ.get('HF_HOME') or cache/'huggingface').expanduser()
    hf_path = Path(os.environ.get('HF_TOKEN_PATH') or hf_home/'token').expanduser()
    for path in (support/'huggingface.token', hf_path):
        try:
            with path.open(encoding='utf-8') as source:
                raw = source.read(4097)
            token = clean(raw) if len(raw) <= 4096 else ''
            if token:
                return token
        except (OSError, UnicodeError):
            pass
    return ''


def defaults(hw=None, support=None):
    hw, support = hw or hardware(), support or support_dir()
    chosen = [m['id'] for m in CATALOG if m['default'] and hw['ram_gib'] >= m['min_ram_gib']]
    cfg = dict(mode='combined' if hw['server_supported'] else 'client', server_role='full',
               connection_mode='connect', t2med_url='https://127.0.0.1:16567/aps/fhir/api/r4',
               t2med_insecure=False, commander_url=DEFAULT_COMMANDER_URL, commander_token='',
               network='local', listen_host='0.0.0.0', auth_enabled=False, server_token='',
               remote_llm_url='', remote_llm_token='', selected_models=chosen,
               quality_models={m['quality']: m['id'] for m in CATALOG if m['id'] in chosen},
               memory_mode='serial', diarization_mode='serial', asr_on_demand=True, diarization=True, hf_token='',
               fields=list(DEFAULT_DOCUMENT_FIELDS), prompt=(ROOT/'prompt_documentation.txt').read_text())
    saved = support / 'installer.json'
    if saved.is_file():
        try:
            previous = json.loads(saved.read_text())
            cfg.update({k:v for k,v in previous.items() if k in cfg and k not in SECRET_FIELDS})
            if 'diarization_mode' not in previous:
                cfg['diarization_mode']='resident' if cfg['memory_mode']=='parallel' else 'serial'
        except (OSError, ValueError):
            pass
    try:
        import kienzledoku_config as client
        old = client.load(support/'config.toml')
        if (support/'config.toml').exists():
            cfg.update(t2med_url=old['connection']['target'], connection_mode=old['connection']['mode'],
                       t2med_insecure=old['connection']['allow_insecure_tls'], commander_url=old['commander']['url'])
    except (OSError, ValueError):
        pass
    prompt = support/'commander/prompt.txt'
    if prompt.is_file():
        cfg['prompt'] = prompt.read_text()
    cfg['hf_token'] = huggingface_token(support)
    return cfg


def bootstrap(hw=None, support=None):
    hw = hw or hardware()
    models = []
    for model in CATALOG:
        entry = dict(model)
        entry['supported'] = bool(hw['server_supported'] and hw['ram_gib'] >= model['min_ram_gib'])
        entry['reason'] = '' if entry['supported'] else 'Für lokalen Betrieb mindestens %s GB gemeinsamer Arbeitsspeicher erforderlich.' % model['min_ram_gib']
        models.append(entry)
    return dict(version=VERSION, hardware=hw, models=models,production_key=production_build(ROOT),
                fields=[dict(id=f,label=DOCUMENT_LABELS[f],default=f in DEFAULT_DOCUMENT_FIELDS) for f in DOCUMENT_FIELDS],
                defaults=defaults(hw,support), default_prompt=(ROOT/'prompt_documentation.txt').read_text(), docs_url=DOCS_URL)


def address(value):
    if not isinstance(value,str) or any(ord(c)<33 for c in value):
        raise ValueError('Bitte eine vollständige Commander-Adresse eingeben.')
    p=urlsplit(value)
    if p.scheme not in ('http','https') or not p.hostname or not p.port or p.path not in ('','/') or p.username is not None or p.query or p.fragment:
        raise ValueError('Commander-Adresse: http(s)://Rechner:Port ohne weitere Pfade.')
    return value.rstrip('/')


def validate(cfg, hw=None):
    hw=hw or hardware()
    if not isinstance(cfg,dict): raise ValueError('Installationsauswahl fehlt.')
    allowed=set(defaults(hw,Path('/nonexistent')))
    if set(cfg)!=allowed: raise ValueError('Unvollständige oder unbekannte Installationseinstellungen.')
    for field,choices in [('mode',('client','server','combined')),('server_role',('full','asr','llm')),('connection_mode',('direct','connect')),('network',('local','lan')),('memory_mode',('serial','parallel')),('diarization_mode',tuple(DIARIZATION_MODES))]:
        if cfg[field] not in choices: raise ValueError('Ungültige Auswahl: '+field)
    for field in ('t2med_insecure','auth_enabled','asr_on_demand','diarization'):
        if type(cfg[field]) is not bool: raise ValueError('Ungültige Einstellung: '+field)
    for field in SECRET_FIELDS:
        token=cfg[field]
        if not isinstance(token,str) or len(token)>4096 or any(c.isspace() for c in token): raise ValueError('Ungültiges Token.')
    address(cfg['commander_url'])
    if cfg['remote_llm_url']: address(cfg['remote_llm_url'])
    import kienzledoku_config as client
    c=client.defaults(); c['connection'].update(target=cfg['t2med_url'],mode=cfg['connection_mode'],allow_insecure_tls=cfg['t2med_insecure']); client.validate(c)
    fields=validate_fields(cfg['fields'])
    if list(fields)!=cfg['fields']: raise ValueError('Dokumentationsfelder müssen in der vorgesehenen Reihenfolge stehen.')
    if not isinstance(cfg['prompt'],str) or not cfg['prompt'].strip() or len(cfg['prompt'])>65536: raise ValueError('Bitte einen Prompt mit höchstens 65.536 Zeichen eingeben.')
    if not isinstance(cfg['selected_models'],list) or len(set(cfg['selected_models']))!=len(cfg['selected_models']): raise ValueError('Ungültige Modellauswahl.')
    models={m['id']:m for m in CATALOG}
    if any(m not in models for m in cfg['selected_models']): raise ValueError('Unbekanntes Modell.')
    if not isinstance(cfg['quality_models'],dict) or set(cfg['quality_models'])-set(GRADES): raise ValueError('Ungültige Stufenzuordnung.')
    server=cfg['mode']!='client'
    local_llm=server and cfg['server_role']!='asr' and not cfg['remote_llm_url']
    if server:
        mac_version=platform.mac_ver()[0] if sys.platform=='darwin' else ''
        if mac_version and tuple(map(int,mac_version.split('.')[:2])) < (14,0):
            raise ValueError('Lokale KI-Laufzeiten benötigen macOS 14 oder neuer.')
        if not hw['server_supported']: raise ValueError('Lokaler KI-Server benötigt Apple Silicon mit mindestens 16 GB Arbeitsspeicher. Der Client kann einen anderen Commander verwenden.')
        if not isinstance(cfg['listen_host'],str) or not re.fullmatch(r'[A-Za-z0-9.:-]{1,253}',cfg['listen_host']): raise ValueError('Ungültige Serveradresse.')
        if cfg['auth_enabled'] and not cfg['server_token']:
            # Empty means keep an existing token; confirmed during install.
            pass
    if local_llm:
        if not cfg['selected_models'] or not cfg['quality_models']: raise ValueError('Mindestens ein Modell und eine aktive Verarbeitungsstufe auswählen.')
        for mid in cfg['selected_models']:
            if hw['ram_gib']<models[mid]['min_ram_gib']: raise ValueError(models[mid]['label']+': zu wenig gemeinsamer Arbeitsspeicher.')
        for grade,mid in cfg['quality_models'].items():
            if mid not in cfg['selected_models'] or models[mid]['quality']!=grade: raise ValueError('Jede Stufe benötigt ein installiertes Modell dieser Stufe.')
            audio=cfg['server_role']!='llm'
            reserve=4 if audio and cfg['memory_mode']=='parallel' else 0
            if audio and cfg['diarization'] and (cfg['diarization_mode']=='resident' or
                    cfg['diarization_mode']=='with_asr' and cfg['memory_mode']=='parallel'):
                reserve+=6
            if hw['ram_gib']<models[mid]['min_ram_gib']+reserve:
                raise ValueError('Für gleichzeitig geladene Modelle reicht die geschätzte Speicherreserve nicht. Bitte Sprechertrennung oder Modellbetrieb seriell wählen.')
    return cfg


def plan(cfg,hw=None):
    validate(cfg,hw)
    server=cfg['mode']!='client'; client=cfg['mode']!='server'
    llm=server and cfg['server_role']!='asr' and not cfg['remote_llm_url']
    lines=[]
    if client: lines += ['kienzledoku record und Connect installieren', 'T2med: '+cfg['t2med_url']]
    if server:
        lines += ['Commander installieren: '+('nur auf diesem Mac' if cfg['network']=='local' else 'im Praxisnetz erreichbar'),
                  'Zugangstoken: '+('aktiviert' if cfg['auth_enabled'] else 'ausgeschaltet'),
                  'Modellbetrieb: '+('seriell' if cfg['memory_mode']=='serial' else 'parallel'),
                  'Whisper: '+('erst bei Bedarf laden' if cfg['asr_on_demand'] else 'beim Start laden')]
        if cfg['server_role']!='llm' and cfg['diarization']:
            lines += ['Sprechertrennung: '+DIARIZATION_MODES[cfg['diarization_mode']],
                      'Sprechertrennung auf dem Mac: ca. 6 GB Arbeitsreserve einplanen (Richtwert, abhängig vom Gespräch).']
        if cfg['remote_llm_url']: lines += ['LLM über '+cfg['remote_llm_url']]
    if llm:
        by_id={m['id']:m for m in CATALOG}
        lines += [GRADE_LABELS[g]+': '+by_id[m]['label'] for g,m in cfg['quality_models'].items()]
    return dict(summary=lines,download_bytes=sum(m['bytes'] for m in CATALOG if llm and m['id'] in cfg['selected_models']))


def atomic_write(path,data,mode=0o600):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(data if isinstance(data,bytes) else data.encode()); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,mode); os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''): h.update(block)
    return h.hexdigest()


def download(url,destination,expected,progress=lambda text:None,cancel=None):
    destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if destination.exists() and sha256(destination)==expected:
        progress('Geprüft, wird wiederverwendet: '+destination.name)
        return destination
    partial=destination.with_name(destination.name+'.part')
    progress('Download: '+destination.name)
    try:
        with urlopen(Request(url,headers={'User-Agent':'kienzledoku-installer/1.8'}),timeout=60) as response, open(partial,'wb') as target:
            total=int(response.headers.get('Content-Length') or 0); received=0; last=0
            while True:
                if cancel and cancel.is_set(): raise InterruptedError('Installation abgebrochen.')
                chunk=response.read(2*1024*1024)
                if not chunk: break
                target.write(chunk); received+=len(chunk)
                if time.monotonic()-last>2:
                    progress('%s: %.0f MB%s' % (destination.name,received/1e6,(' / %.0f MB (%.0f %%)'%(total/1e6,min(100,received*100/total))) if total else '')); last=time.monotonic()
        progress(destination.name+': Download vollständig; Prüfsumme wird geprüft.')
        if sha256(partial)!=expected: raise ValueError('Die Prüfsumme stimmt nicht: '+destination.name)
        os.replace(partial,destination)
    finally:
        if partial.exists(): partial.unlink()
    return destination


def extract_archive(archive,directory):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(directory,filter='data')


def require_closed_record(support):
    """Do not restart Commander while a patient's Record window is open."""
    import fcntl
    for path in (Path(support)/'sessions').glob('*/record.lock'):
        with path.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Bitte zuerst das offene Patientenfenster in kienzledoku record schließen und die Installation erneut starten.') from None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def commander_toml(cfg,version_root,support):
    q=lambda s:json.dumps(str(s),ensure_ascii=False)
    roles=[]
    if cfg['server_role']!='llm': roles+=['asr']+(['diar'] if cfg['diarization'] else [])
    if cfg['server_role']!='asr' or cfg['remote_llm_url']: roles+=['llm']
    memory=hardware()['ram_gib']; tier=24 if memory>=32 else (16 if memory>=24 else 8)
    data=['[server]','host = '+q('127.0.0.1' if cfg['network']=='local' else cfg['listen_host']),'port = 8185',
          'auth_enabled = '+str(cfg['auth_enabled']).lower(),'token_env = "KIENZLEDOKU_COMMANDER_TOKEN"',
          '', '[gpu]', 'vram_gib = '+str(tier), '', '[policy]', 'memory_mode = '+q(cfg['memory_mode']),
          'diarization_mode = '+q(cfg['diarization_mode']),
          'asr_on_demand = '+str(cfg['asr_on_demand']).lower(),'enabled_roles = '+json.dumps(roles),
          'enabled_fields = '+json.dumps(cfg['fields']),
          'default_quality = '+q(next((g for g in GRADES if g in cfg['quality_models']), 'auto') if not cfg['remote_llm_url'] and cfg['server_role']!='asr' else 'auto'),
          'load_timeout = 600', 'backend_timeout = 7200', 'queue_timeout = 3600',
          '', '[backends]', 'platform = "macos"', 'prompt_path = '+q(support/'commander/prompt.txt'),
          'control_dir = '+q(support/'commander/run'), 'llama_binary = '+q(version_root/'llama/llama-server'),
          'asr_url = "http://127.0.0.1:8179"','diar_url = "http://127.0.0.1:8183"','llm_url = "http://127.0.0.1:8086"',
          'asr_command = '+json.dumps([str(version_root/'asr-venv/bin/python'),str(version_root/'local-ai-macos/asr_server_mlx.py')]),
          'diar_command = '+json.dumps([str(version_root/'diar-venv/bin/python'),str(version_root/'local-ai-macos/diarization_server_mps.py')]),
          'asr_model_path = '+q(support/'models/whisper-large-v3-mlx'),'diar_model_path = '+q(support/'models/pyannote-community-1'),
          '', '[remote_llm]', 'url = '+q(cfg['remote_llm_url']), 'token_env = "KIENZLEDOKU_REMOTE_LLM_TOKEN"']
    models={m['id']:m for m in CATALOG}
    if not cfg['remote_llm_url'] and cfg['server_role']!='asr':
        for grade,mid in cfg['quality_models'].items():
            m=models[mid]
            data += ['', '[models.'+grade+']', 'path = '+q(support/'models'/mid/m['filename']), 'model_id = '+q(mid),
                     'label = '+q(m['label']), 'context = 32768','slots = 1','kv = "q8_0"']
        for mid in cfg['selected_models']:
            m=models[mid]
            reserve=8 if cfg['diarization_mode']=='resident' else 6
            data += ['', '[benchmark_models.'+q(mid)+']', 'path = '+q(support/'models'/mid/m['filename']),
                     'label = '+q(m['label']), 'context = 32768', 'slots = 1', 'kv = "q8_0"',
                     'parallel_available = '+str(memory >= m['min_ram_gib']+reserve).lower()]
    return '\n'.join(data)+'\n'


class Installer:
    def __init__(self,support=None,hw=None):
        self.support=Path(support or support_dir()); self.hw=hw or hardware()
        self.cancel=threading.Event(); self.lock=threading.Lock(); self.proc=None
        self.state=dict(running=False,done=False,error='',step='',message='',progress=0,logs=[],client_installed=False,commander_url='',server_token='',launch_url='')

    def snapshot(self):
        with self.lock: return dict(self.state,logs=list(self.state['logs']))

    def report(self,message,progress=None):
        with self.lock:
            self.state['message']=message
            if progress is not None: self.state['progress']=progress
            self.state['logs']=(self.state['logs']+[message])[-100:]

    def _stop_commander(self,domain,label):
        from kienzledoku_commander.macos_processes import cleanup_after_stop
        subprocess.run(['/bin/launchctl','bootout',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if cleanup_after_stop(self.support/'commander/run'):
            self.report('Verwaiste eigene Modellprozesse bereinigt.')

    def _wait_commander(self):
        data=tomllib.loads((self.support/'commander/config.toml').read_text())
        policy=data['policy'];roles=set(policy['enabled_roles'])
        parallel=policy.get('memory_mode')=='parallel'
        diar_mode=policy.get('diarization_mode') or ('resident' if parallel else 'serial')
        asr='asr' in roles and not policy.get('asr_on_demand',False)
        required=set()
        if asr:required.add('asr')
        if 'diar' in roles and (diar_mode=='resident' or diar_mode=='with_asr' and asr):required.add('diar')
        if 'llm' in roles and parallel and not data.get('remote_llm',{}).get('url'):required.add('llm')
        # Each sequential cold start has its own configured limit.
        deadline=time.monotonic()+30+max(1,len(required))*policy.get('load_timeout',600)
        last_reachable=time.monotonic()
        credentials=json.loads((self.support/'commander/credentials.json').read_text())
        headers={'Authorization':'Bearer '+credentials['KIENZLEDOKU_COMMANDER_TOKEN']} if data['server'].get('auth_enabled') else {}
        announced=None
        while True:
            if self.cancel.is_set():raise InterruptedError('Installation abgebrochen.')
            try:
                with urlopen(Request('http://127.0.0.1:8185/v1/runtime/status',headers=headers),timeout=2) as response:
                    status=json.loads(response.read(65536))
                last_reachable=time.monotonic()
                if status.get('last_error'):
                    raise RuntimeError('Commander ist erreichbar, konnte aber ein Modell nicht laden. Die vorherige Konfiguration wird wiederhergestellt.')
                loaded=status.get('loaded',{})
                missing=required-{role for role in required if loaded.get(role)}
                if not missing and not status.get('transition_running'):
                    with urlopen(Request('http://127.0.0.1:8185/health',headers=headers),timeout=2) as response:
                        if response.status==200:return
                names={'asr':'Whisper','diar':'Sprechertrennung','llm':'LLM'}
                message='Commander erreichbar – Modelle werden geladen: '+', '.join(names[r] for r in ('asr','diar','llm') if r in missing)
                if not missing:message='Commander schließt den Modellstart ab.'
                if message!=announced:self.report(message);announced=message
            except (OSError,ValueError,KeyError):pass
            if time.monotonic()-last_reachable>=30:
                raise RuntimeError('Commander ist nicht erreichbar. Die vorherige Konfiguration wird wiederhergestellt.')
            if time.monotonic()>=deadline:
                raise RuntimeError('Commander wurde innerhalb der Modellladezeit nicht bereit. Die vorherige Konfiguration wird wiederhergestellt.')
            time.sleep(.5)

    def run(self,argv,env=None):
        if self.cancel.is_set(): raise InterruptedError('Installation abgebrochen.')
        # Only expose known high-level messages. pip/download error output could contain credentials.
        env=dict(os.environ if env is None else env)
        for key in ('PYTHONHOME','PYTHONPATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH'):
            env.pop(key,None)
        with tempfile.TemporaryFile() as output:
            self.proc=subprocess.Popen([str(x) for x in argv],stdout=output,stderr=output,env=env,start_new_session=True)
            try:
                while self.proc.poll() is None:
                    if self.cancel.wait(.2):
                        os.killpg(self.proc.pid,signal.SIGTERM)
                        try: self.proc.wait(timeout=10)
                        except subprocess.TimeoutExpired: os.killpg(self.proc.pid,signal.SIGKILL); self.proc.wait()
                        raise InterruptedError('Installation abgebrochen.')
                if self.proc.returncode: raise RuntimeError('Installationsschritt fehlgeschlagen: '+Path(str(argv[0])).name+' (Exit '+str(self.proc.returncode)+'). Bitte Verbindung, Speicherplatz und gegebenenfalls den Hugging-Face-Zugang prüfen.')
            finally: self.proc=None

    def start(self,cfg):
        validate(cfg,self.hw)
        require_closed_record(self.support)
        if cfg["mode"] != "client" and cfg["server_role"] != "llm" and cfg["diarization"] and not cfg["hf_token"]:
            marker=self.support/"models/pyannote-community-1/.kienzledoku-revision"
            if not marker.is_file() or marker.read_text().strip()!=PYANNOTE_REV:
                raise ValueError("Für die Sprechertrennung bitte zuerst das Hugging-Face-Token eingeben und die Modellbedingungen bestätigen, oder Sprechertrennung abwählen.")
        with self.lock:
            if self.state['running']: raise ValueError('Die Installation läuft bereits.')
            self.cancel.clear(); self.state.update(running=True,done=False,error='',progress=0,logs=[])
        threading.Thread(target=self._work,args=(dict(cfg),),daemon=True).start()

    def _work(self,cfg):
        from installer.update_macos import update_guard, preserve_unselected, stop_idle_launchers
        try:
            with update_guard(self.support):
                self._preserved_versions=preserve_unselected(self.support,Path.home(),cfg['mode']!='client',cfg['mode']!='server')
                if cfg['mode']!='server':stop_idle_launchers(Path.home())
                self._update_guard_held=True
                try:self._work_locked(cfg)
                finally:self._update_guard_held=False
        except Exception as exc:
            message=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Updateprüfung fehlgeschlagen; keine Freigabe zur Bereinigung.'
            with self.lock:self.state.update(running=False,error=message)
            self.report(message)

    def _work_locked(self,cfg):
        version=None
        try:
            self.report('Installation vorbereiten',2)
            self.support.mkdir(parents=True,exist_ok=True,mode=0o700)
            os.chmod(self.support,0o700)
            server=cfg['mode']!='client'; client=cfg['mode']!='server'
            client_files=('kienzledoku_window','kienzleconnect','kienzledoku_record_app','kienzledoku_connect_app')
            if production_build(ROOT):
                client_files+=('libkienzledoku_product.dylib','release.json')
            if client:
                for name in client_files:
                    if not (ROOT/name).is_file():
                        raise RuntimeError('Installationspaket unvollständig: '+name+' fehlt. Bitte einen korrigierten Installer verwenden.')
            llm=server and cfg['server_role']!='asr' and not cfg['remote_llm_url']
            asr=server and cfg['server_role']!='llm'
            size=plan(cfg,self.hw)['download_bytes']+(5*2**30 if asr else 0)+3*2**30
            existing=0
            if llm:
                for m in CATALOG:
                    path=self.support/'models'/m['id']/m['filename']
                    if m['id'] in cfg['selected_models'] and path.is_file() and path.stat().st_size==m['bytes']:
                        existing+=m['bytes']
            if shutil.disk_usage(self.support).free<max(2*2**30,size-existing): raise ValueError('Für die gewählten Komponenten ist nicht genug freier Speicherplatz vorhanden.')
            version=self.support/'versions'/(VERSION+'-'+secrets.token_hex(4)); version.mkdir(parents=True)
            from installer.update_macos import mark_version
            mark_version(version)
            for path in ROOT.glob('kienzledoku*.py'): shutil.copy2(path,version/path.name)
            for name in ('kienzledoku_commander','local-ai-macos','assets','installer'):
                shutil.copytree(ROOT/name,version/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for name in ('LICENSE','NOTICE','prompt_documentation.txt','requirements-asr-client.txt',*client_files):
                if (ROOT/name).is_file(): shutil.copy2(ROOT/name,version/name)
            self.report('Eigene Python-Laufzeit bereitstellen',7)
            packaged=ROOT.parent/'runtime/python'
            if not packaged.is_dir():
                archive=self.support/'downloads/python.tar.gz'; info=LOCKS['python_'+self.hw['arch']]
                download(info['url'],archive,info['sha256'],self.report,self.cancel)
                extract_archive(archive,version/'runtime'); python=version/'runtime/python/bin/python3.12'
            else:
                shutil.copytree(packaged,version/'runtime/python',symlinks=True)
                python=version/'runtime/python/bin/python3.12'
            self.run([python,'-m','venv',version/'venv']); runtime=version/'venv/bin/python'
            if client:
                self.report('Client-Komponenten einrichten',12)
                wheelhouse=ROOT.parent/'wheelhouse'
                options=['--no-index','--find-links',wheelhouse] if wheelhouse.is_dir() else []
                self.run([runtime,'-m','pip','install',*options,'-r',version/'requirements-asr-client.txt'])
                self.run([runtime,version/'kienzledoku_vad.py'])
            if llm:
                self.report('Metal-Laufzeit bereitstellen',18)
                info=LOCKS['llama_'+self.hw['arch']]; archive=self.support/'downloads/llama.tar.gz'
                download(info['url'],archive,info['sha256'],self.report,self.cancel)
                extract_archive(archive,version/'llama-unpack')
                executable=next((version/'llama-unpack').rglob('llama-server'))
                shutil.copytree(executable.parent,version/'llama',symlinks=True)
                for m in CATALOG:
                    if m['id'] in cfg['selected_models']:
                        self.report('Modell installieren: '+m['label'],25)
                        download(m['url'],self.support/'models'/m['id']/m['filename'],m['sha256'],self.report,self.cancel)
            if asr:
                self.report('Whisper-Laufzeit einrichten',45)
                self.run([python,'-m','venv',version/'asr-venv'])
                from installer.locked_dependencies import install_locked
                install_locked(version/'asr-venv/bin/python', ROOT/'installer/dependency-locks/macos-asr-py312.txt', version/'asr-dependencies.json', self.run)
                for name,digest in WHISPER_FILES.items():
                    download('https://huggingface.co/mlx-community/whisper-large-v3-mlx/resolve/'+WHISPER_REV+'/'+name,self.support/'models/whisper-large-v3-mlx'/name,digest,self.report,self.cancel)
            if asr and cfg['diarization']:
                self.report('Sprechertrennung einrichten',60)
                self.run([python,'-m','venv',version/'diar-venv'])
                from installer.locked_dependencies import install_locked
                install_locked(version/'diar-venv/bin/python', ROOT/'installer/dependency-locks/macos-diar-py312.txt', version/'diar-dependencies.json', self.run, dict(os.environ,PYANNOTE_METRICS_ENABLED='0'))
                env=dict(os.environ,HF_TOKEN=cfg['hf_token'],HF_HUB_DISABLE_TELEMETRY='1',PYANNOTE_METRICS_ENABLED='0')
                self.run([version/'diar-venv/bin/python',version/'installer/download_diarization.py',self.support/'models/pyannote-community-1'],env=env)
            if self.cancel.is_set(): raise InterruptedError('Installation abgebrochen.')
            self.report('Konfiguration und Programme fertigstellen',85)
            self._activate(cfg,version,runtime,server,client)
            self.report('Alte Programmstände und Starter bereinigen',95)
            from installer.update_macos import complete_update
            complete_update(self.support,Path.home(),version,preserved=getattr(self,'_preserved_versions',{}),
                            expected_roles=(('record','connect') if client else ())+ (('commander',) if server else ()))
            self.report('Installation abgeschlossen',100)
            server_host='127.0.0.1'
            if cfg['network']=='lan':
                server_host=cfg['listen_host'] if cfg['listen_host'] not in ('0.0.0.0','::') else next(iter(self.hw.get('lan_addresses',[])),'RECHNER-IP')
            server_url='http://'+('['+server_host+']' if ':' in server_host else server_host)+':8185'
            scheme='kienzledoku-record' if cfg['connection_mode']=='direct' else 'kienzledoku'
            launch_url=scheme+'://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}'
            with self.lock: self.state.update(done=True,client_installed=client,commander_url=server_url if server else cfg['commander_url'],server_token=cfg['server_token'] if server and cfg['auth_enabled'] else '',launch_url=launch_url if client else '')
        except Exception as exc:
            # Exceptions deliberately omit dependency output and secret-bearing URLs.
            message=str(exc) if isinstance(exc,(ValueError,InterruptedError,RuntimeError)) else 'Installation fehlgeschlagen ('+type(exc).__name__+'). Bitte Verbindung und Schreibrechte prüfen.'
            with self.lock: self.state['error']=message
            self.report(message)
        finally:
            with self.lock: self.state['running']=False

    def _activate(self,cfg,version,runtime,server,client):
        if not getattr(self,'_update_guard_held',False):require_closed_record(self.support)
        import kienzledoku_config as record
        client_cfg=record.load(self.support/'config.toml')
        client_cfg['connection'].update(mode=cfg['connection_mode'],target=cfg['t2med_url'],allow_insecure_tls=cfg['t2med_insecure'])
        client_cfg['commander'].update(enabled=True,url='http://127.0.0.1:8185' if server else cfg['commander_url'],token_file='')
        client_cfg['record']['diarization']=cfg['diarization']
        commander=self.support/'commander'; commander.mkdir(exist_ok=True,mode=0o700)
        credentials_path=commander/'credentials.json'
        credentials=json.loads(credentials_path.read_text()) if credentials_path.exists() else {}
        if server and cfg['auth_enabled']:
            cfg['server_token']=cfg['server_token'] or credentials.get('KIENZLEDOKU_COMMANDER_TOKEN') or secrets.token_urlsafe(32)
            credentials['KIENZLEDOKU_COMMANDER_TOKEN']=cfg['server_token']
        else: credentials.pop('KIENZLEDOKU_COMMANDER_TOKEN',None)
        if cfg['remote_llm_token']: credentials['KIENZLEDOKU_REMOTE_LLM_TOKEN']=cfg['remote_llm_token']
        if not cfg['remote_llm_url']: credentials.pop('KIENZLEDOKU_REMOTE_LLM_TOKEN',None)
        # Build apps before publishing new settings.
        pending=[]
        if client:
            for mode in ('record','connect'):
                pending.append(self._app(version,runtime,mode))
        candidate=version/'commander-candidate.toml'
        if server:
            control=commander/'run'
            control.mkdir(exist_ok=True,mode=0o700)
            os.chmod(control,0o700)
            atomic_write(candidate,commander_toml(cfg,version,self.support))
            # Validate without loading models or binding a service.
            self.run([runtime,version/'installer/service_main.py','--check-config',str(candidate),str(credentials_path)],env=dict(os.environ,**credentials))
        self.run([runtime,'-m','compileall','-q',str(version)])
        changed=[]; previous_plist=None; activated=False; published=[]
        label='de.kienzledoku.commander'; plist=Path.home()/'Library/LaunchAgents'/f'{label}.plist'; domain='gui/'+str(os.getuid())
        def replace(path,raw):
            changed.append((path,path.read_bytes() if path.exists() else None)); atomic_write(path,raw)
        try:
            if server:
                previous_plist=plist.read_bytes() if plist.exists() else None
                self._stop_commander(domain,label)
                replace(commander/'prompt.txt',cfg['prompt'])
                replace(credentials_path,json.dumps(credentials))
                replace(commander/'config.toml',candidate.read_bytes())
                service={'Label':label,'ProgramArguments':[str(runtime),str(version/'installer/service_main.py'),str(commander/'config.toml'),str(credentials_path)],'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'WorkingDirectory':str(version),'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'},'ThrottleInterval':10,'ProcessType':'Background','ExitTimeOut':120}
                replace(plist,plistlib.dumps(service))
            if client:
                changed.append((self.support/'config.toml',(self.support/'config.toml').read_bytes() if (self.support/'config.toml').exists() else None))
                record.save(client_cfg,self.support/'config.toml')
                token=cfg['server_token'] if server and cfg['auth_enabled'] else cfg['commander_token'] if not server else ''
                # Explicit empty value disables a previously stored Commander token.
                replace(self.support/'commander.token',token)
                for staged,destination in pending:
                    backup=version/(destination.stem+'-previous.app')
                    if destination.exists(): destination.rename(backup)
                    staged.rename(destination)
                    published.append(destination)
                    self.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister','-f',destination])
            if server:
                activated=True
                self.run(['/bin/launchctl','bootstrap',domain,plist])
                self.run(['/bin/launchctl','kickstart',domain+'/'+label])
                self._wait_commander()
            if server and cfg['server_role'] != 'llm' and cfg['diarization']:
                # Installation credential only: separate private file, never
                # in installer.json, Commander settings, plist or logs.
                replace(self.support/'huggingface.token',cfg['hf_token'])
            replace(self.support/'installer.json',json.dumps({k:v for k,v in cfg.items() if k not in SECRET_FIELDS},ensure_ascii=False,indent=2))
        except Exception:
            if activated:self._stop_commander(domain,label)
            for path,previous in reversed(changed):
                if previous is None: path.unlink(missing_ok=True)
                else: atomic_write(path,previous)
            for staged,destination in pending:
                backup=version/(destination.stem+'-previous.app')
                if backup.exists():
                    if destination.exists(): shutil.rmtree(destination)
                    backup.rename(destination)
                elif destination in published and destination.exists():
                    shutil.rmtree(destination)
            if server and previous_plist:
                result=subprocess.run(['/bin/launchctl','bootstrap',domain,plist],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if result.returncode:
                    raise RuntimeError('Vorherige Einstellungen wiederhergestellt, aber der Commander konnte nicht erneut gestartet werden.') from None
                # A cancelled new install still needs a working old service.
                cancelled=self.cancel.is_set();self.cancel.clear()
                try:self._wait_commander()
                finally:
                    if cancelled:self.cancel.set()
            raise

    def _app(self,version,runtime,mode):
        name='kienzledoku '+mode+'.app'; app=version/name
        contents=app/'Contents'; (contents/'MacOS').mkdir(parents=True); (contents/'Resources').mkdir()
        shutil.copy2(version/f'kienzledoku_{mode}_app',contents/'MacOS/kienzledoku')
        shutil.copy2(version/'assets/kienzledoku-record.icns',contents/'Resources/app.icns')
        info=dict(CFBundleIdentifier='de.kienzledoku.app' if mode=='record' else 'de.kienzledoku.connect',CFBundleName='kienzledoku '+mode,CFBundleExecutable='kienzledoku',CFBundlePackageType='APPL',CFBundleVersion=VERSION,CFBundleShortVersionString=VERSION,CFBundleIconFile='app.icns',LSUIElement=True,NSMicrophoneUsageDescription='kienzledoku record benötigt das Mikrofon für die Gesprächsaufzeichnung.',KienzledokuPython=str(runtime),KienzledokuRoot=str(version),KienzledokuMode=mode,CFBundleURLTypes=[dict(CFBundleURLSchemes=['kienzledoku-record' if mode=='record' else 'kienzledoku'])])
        info['NSLocalNetworkUsageDescription']='Kienzledoku verbindet sich mit T2med und Commander im Praxisnetz, um den geöffneten Patienten zu laden und Ihre Dokumentation zu übertragen.'
        info['KienzledokuUpdateLock']=str(self.support/'update.lock')
        atomic_write(contents/'Info.plist',plistlib.dumps(info),0o644)
        self.run(['/usr/bin/codesign','--force','--deep','--sign','-',app])
        self.run(['/usr/bin/codesign','--verify','--deep','--strict',app])
        destination=Path.home()/'Applications'/name; destination.parent.mkdir(exist_ok=True)
        return app,destination
