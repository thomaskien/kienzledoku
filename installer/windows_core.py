"""Windows adapter for the shared installer UI; mutations stay in the existing engine."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

import kienzledoku_config as client
from kienzledoku_document import DEFAULT_DOCUMENT_FIELDS, DOCUMENT_FIELDS, DOCUMENT_LABELS, validate_fields
from kienzledoku_product_key import production_build

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT.parent if (ROOT.parent/'server/models.json').exists() else ROOT
SERVER = PAYLOAD/'server' if (PAYLOAD/'server').exists() else ROOT/'server-windows'
BRIDGE = PAYLOAD/'WizardBridge.ps1' if (PAYLOAD/'WizardBridge.ps1').exists() else ROOT/'windows/WizardBridge.ps1'
VERSION = '1.8.1'
from installer.options import SERVER_ROLES, ASR_MODELS, local_role
CATALOG = json.loads((SERVER/'models.json').read_text(encoding='utf-8-sig'))
GRADES = dict(basis='Basis', gruendlich='Gründlich', sehr_gruendlich='Sehr gründlich')
SECRETS = ('commander_token', 'server_token', 'remote_llm_token', 'remote_diar_token', 'hf_token')
DOCS = 'https://github.com/thomaskien/kienzledoku#t2med-einrichten-und-verwenden'


def support_dir():
    return Path(os.environ['LOCALAPPDATA'])/'kienzledoku-installer'


def powershell():
    return str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')


def ps_args(action, *extra):
    return [powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(BRIDGE), '-Action', action, *map(str, extra)]


def read_json(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return default


def inspect_system():
    result = subprocess.run(ps_args('Inspect'), capture_output=True, timeout=45,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode: raise ValueError('Windows-Voraussetzungen konnten nicht gelesen werden. Bitte den Installer erneut öffnen.')
    return json.loads(result.stdout.decode('utf-8-sig'))


def address(value):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value): raise ValueError('Vollständige Commander-Adresse eingeben.')
    p = urlsplit(value)
    if p.scheme not in ('http','https') or not p.hostname or not p.port or p.path not in ('','/') or p.username is not None or p.query or p.fragment:
        raise ValueError('Commander-Adresse: http(s)://Rechner:Port ohne weitere Pfade.')
    return value.rstrip('/')


def hardware(info):
    h = info.get('hardware') or {}
    gpus = h.get('Gpus') or []
    gpu = next((g for g in gpus if g.get('Index') == (info.get('previous') or {}).get('GpuIndex') and g.get('VramMiB',0)>=3840), next((g for g in gpus if g.get('VramMiB',0)>=3840),gpus[0] if gpus else {}))
    ram = h.get('RamBytes', 0) / 2**30
    return dict(platform='win32', arch=h.get('Architecture', 'AMD64'), ram_gib=round(ram,1),
                server_supported=h.get('Build',0) >= 22000 and h.get('Architecture') == 'AMD64' and gpu.get('VramMiB',0) >= 3840 and ram >= 19.5,
                vram_mib=gpu.get('VramMiB',0), gpu_index=gpu.get('Index',0), gpus=gpus,
                lan_addresses=[a['IPAddress'] for a in h.get('Addresses',[])], info=info)


def standard_prompt():
    # Python 3.12 on Windows can otherwise use cp1252 for this UTF-8 resource.
    return (ROOT/'prompt_documentation.txt').read_text(encoding='utf-8')


def restored_prompt(previous):
    standard = standard_prompt()
    if not previous:
        return standard
    # Repair only a byte-for-byte known broken standard from 1.7.2.
    # Never reinterpret or replace a user's customized prompt.
    for encoding in ('cp1252', 'latin1'):
        try: broken = standard.encode('utf-8').decode(encoding)
        except UnicodeError: continue
        if previous.replace('\r\n', '\n') == broken:
            return standard
    return previous


def defaults(hw, support):
    old = hw.get('info', {}).get('previous') or {}
    cc = client.load()
    info = hw.get('info', {})
    from kienzledoku_commander_client import configured_client
    commander_token=configured_client(cc['commander']).token
    cfg = dict(mode='combined' if info.get('client') and old else 'server' if old else 'client', server_role=old.get('ServerRole','full'),
               connection_mode=cc['connection']['mode'], t2med_url=cc['connection']['target'], t2med_insecure=cc['connection']['allow_insecure_tls'],
               commander_url=cc['commander']['url'], commander_token=commander_token,
               network=old.get('NetworkMode','local'), listen_host=old.get('NetworkAddress') or next(iter(hw['lan_addresses']),''),
               auth_enabled=old.get('AuthEnabled',False), server_token='', remote_llm_url=old.get('RemoteLlmUrl',''), remote_llm_token='',remote_diar_url=old.get('RemoteDiarUrl',''),remote_diar_token='',asr_model=old.get('AsrModel','turbo-int8' if hw['vram_mib']<7936 else 'large-v3'),
               selected_models=old.get('Models',['qwen4-q4']), quality_models=old.get('QualityModels',{}),
               memory_mode='parallel' if old.get('ParallelModel') else 'serial', parallel_model=old.get('ParallelModel',''),
               default_model=old.get('DefaultModel','qwen4-q4'), diarization_mode=old.get('DiarizationMode') or ('resident' if old.get('ParallelModel') else 'serial'),
               asr_on_demand=old.get('AsrOnDemand',True), diarization=old.get('Diarization',True), hf_token='',
               fields=old.get('EnabledFields',list(DEFAULT_DOCUMENT_FIELDS)), prompt=restored_prompt(old.get('PromptText')),
               wsl_ram_gib=old.get('WslRamGiB', next((n for n in (32,28,24,16) if hw['ram_gib']-n >= 3.5),16)),
               gpu_index=hw['gpu_index'], cache_directory=old.get('CacheDirectory',str(Path.home()/'Downloads/kienzledoku-modelle')),
               install_directory=old.get('InstallDirectory',str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/kienzledoku Server')),
               sources='\n'.join(old.get('Sources',[])), audio_cache=old.get('AudioCache','ram'),
               autostart=old.get('Autostart',False), verify=old.get('Verify',True), verify_models=old.get('VerifyModelFiles',True),
               cleanup_staging=old.get('CleanupModelStaging',False), recheck_models=False)
    if not cfg['quality_models']:
        for mid in cfg['selected_models']:
            if mid in CATALOG: cfg['quality_models'].setdefault(CATALOG[mid]['grade'],mid)
    state = Path(os.environ.get('LOCALAPPDATA',''))/'kienzledoku-server'
    for key, path in [('hf_token',Path(old.get('TokenFile') or state/'hf.token')),
                      ('server_token',state/'client.token'),('remote_llm_token',state/'remote-llm.token'),('remote_diar_token',state/'remote-diar.token')]:
        try: cfg[key] = path.read_text(encoding='utf-8-sig').strip()
        except OSError: pass
    if not cfg['hf_token']:
        cfg['hf_token'] = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN','')
        if not cfg['hf_token']:
            hf = Path(os.environ.get('HF_TOKEN_PATH') or Path(os.environ.get('HF_HOME') or Path.home()/'.cache/huggingface')/'token')
            try: cfg['hf_token'] = hf.read_text(encoding='utf-8-sig').strip()
            except OSError: pass
    return cfg


def bootstrap(hw=None, support=None):
    hw = hw or hardware(inspect_system())
    cfg = defaults(hw, support)
    models = []
    for mid, m in CATALOG.items():
        supported = hw['server_supported'] and hw['vram_mib'] >= m['serial_vram_mib']
        models.append(dict(id=mid,label=m['label'],quality=m['grade'],bytes=sum(f['bytes'] for f in m['files']),
                           min_ram_gib=m.get('recommended_wsl_gib',16)+4, supported=supported,
                           serial_vram_mib=m['serial_vram_mib'],parallel_vram_mib=m['parallel_vram_mib'],
                           parallel_supported=bool(m['parallel_vram_mib'] and hw['vram_mib']>=m['parallel_vram_mib']),
                           reason='Benötigt Windows 11, NVIDIA und mindestens %.0f GB VRAM.' % (m['serial_vram_mib']/1024)))
    public_hw = {k:v for k,v in hw.items() if k!='info'}
    return dict(version=VERSION,platform='windows',hardware=public_hw,models=models,defaults=cfg,
                production_key=production_build(ROOT),docs_url=DOCS,
                fields=[dict(id=f,label=DOCUMENT_LABELS[f],default=f in DEFAULT_DOCUMENT_FIELDS) for f in DOCUMENT_FIELDS],
                default_prompt=standard_prompt(),
                prompt_encoding_repaired=bool((hw.get('info',{}).get('previous') or {}).get('PromptText') and
                    cfg['prompt'] != hw['info']['previous']['PromptText']))


def validate(cfg, hw):
    if not isinstance(cfg,dict) or set(cfg)!=set(defaults(hw,None)): raise ValueError('Unvollständige oder unbekannte Einstellungen.')
    for key, choices in dict(mode=('client','server','combined'),server_role=tuple(SERVER_ROLES),asr_model=ASR_MODELS,connection_mode=('direct','connect'),network=('local','lan'),memory_mode=('serial','parallel'),diarization_mode=('resident','with_asr','serial'),audio_cache=('ram','disk')).items():
        if cfg[key] not in choices: raise ValueError('Ungültige Auswahl: '+key)
    for key in ('t2med_insecure','auth_enabled','asr_on_demand','diarization','autostart','verify','verify_models','cleanup_staging','recheck_models'):
        if type(cfg[key]) is not bool: raise ValueError('Ungültige Einstellung: '+key)
    for key in SECRETS:
        if not isinstance(cfg[key],str) or len(cfg[key])>4096 or any(c.isspace() for c in cfg[key]): raise ValueError('Ungültiges Token.')
    address(cfg['commander_url'])
    if cfg['remote_llm_url']: address(cfg['remote_llm_url'])
    if cfg['remote_diar_url']: address(cfg['remote_diar_url'])
    c=client.defaults(); c['connection'].update(target=cfg['t2med_url'],mode=cfg['connection_mode'],allow_insecure_tls=cfg['t2med_insecure']); client.validate(c)
    if list(validate_fields(cfg['fields']))!=cfg['fields']: raise ValueError('Ungültige Dokumentationsfelder.')
    if not isinstance(cfg['prompt'],str) or not cfg['prompt'].strip() or len(cfg['prompt'])>65536: raise ValueError('Prompt fehlt oder ist zu lang.')
    if cfg['mode']=='client': return cfg
    if not hw['server_supported']: raise ValueError('Lokaler Server benötigt Windows 11 x64, NVIDIA ab 4 GB VRAM und mindestens 20 GB RAM. Nur Client benötigt dies nicht.')
    gpu=next((g for g in hw['gpus'] if g['Index']==cfg['gpu_index']),None)
    if not gpu: raise ValueError('NVIDIA-GPU auswählen.')
    if cfg['wsl_ram_gib'] not in (16,24,28,32) or hw['ram_gib']-cfg['wsl_ram_gib']<3.5: raise ValueError('Mindestens 4 GB RAM für Windows freihalten.')
    models=cfg['selected_models']
    if not isinstance(models,list) or (local_role(cfg,'llm') and not models) or len(set(models))!=len(models) or any(m not in CATALOG for m in models): raise ValueError('Mindestens ein gültiges Modell auswählen.')
    for mid in models:
        m=CATALOG[mid]
        if gpu['VramMiB']<m['serial_vram_mib']: raise ValueError(m['label']+': zu wenig VRAM.')
        if cfg['wsl_ram_gib']<m.get('ram_audio_min_wsl_gib',0) and cfg['audio_cache']!='disk': raise ValueError(m['label']+': Whisper-SSD-Sparmodus oder mehr WSL-RAM erforderlich.')
    mapping=cfg['quality_models']
    if not isinstance(mapping,dict) or (local_role(cfg,'llm') and not mapping): raise ValueError('Aktive Qualitätsstufe auswählen.')
    for grade,mid in mapping.items():
        if grade not in GRADES or mid not in models or CATALOG[mid]['grade']!=grade: raise ValueError('Ungültige Modellzuordnung.')
    if local_role(cfg,'llm') and cfg['default_model'] not in mapping.values(): raise ValueError('Standardmodell muss einer aktiven Qualitätsstufe zugeordnet sein.')
    if cfg['memory_mode']=='parallel':
        mid=cfg['parallel_model']
        if mid not in models or not CATALOG[mid]['parallel_vram_mib'] or gpu['VramMiB']<CATALOG[mid]['parallel_vram_mib']: raise ValueError('Für diese GPU freigegebenes Parallelmodell auswählen.')
    if gpu['VramMiB']<7936:
        if cfg['memory_mode']!='serial' or not cfg['asr_on_demand'] or cfg['diarization_mode']!='serial':
            raise ValueError('Unter 8 GB VRAM verschärft seriell und serielle Sprechertrennung wählen.')
        if local_role(cfg,'asr') and cfg['asr_model']!='turbo-int8': raise ValueError('Für diese GPU Whisper Turbo 8 Bit auswählen.')
    if cfg['network']=='lan' and cfg['listen_host'] not in hw['lan_addresses']: raise ValueError('Eine vorhandene LAN-IP auswählen.')
    for key in ('cache_directory','install_directory'):
        import ntpath
        if not isinstance(cfg[key],str) or not ntpath.isabs(cfg[key]) or any(c in cfg[key] for c in '\r\n"'): raise ValueError('Absoluten Windows-Pfad ohne Anführungszeichen eingeben.')
    if cfg['install_directory'].startswith('\\\\'): raise ValueError('Die aktive WSL-Umgebung benötigt ein lokales Laufwerk.')
    return cfg


def plan(cfg, hw=None):
    hw = hw or hardware(inspect_system()); validate(cfg,hw)
    lines=[]
    if cfg['mode']!='server': lines += ['Record und Connect installieren; vorhandene VAD-/Pegelwerte bleiben erhalten.', 'Commander: '+('http://127.0.0.1:8185' if cfg['mode']=='combined' else cfg['commander_url']), 'T2med: '+cfg['t2med_url']]
    if cfg['mode']!='client':
        lines+=['Commander und KI-Dienste in der eigenen Kienzledoku-WSL-Umgebung installieren.',
                'WSL-RAM: %s GB; Netzwerk: %s' % (cfg['wsl_ram_gib'],cfg['network']),
                'LLM: '+('seriell' if cfg['memory_mode']=='serial' else 'parallel: '+CATALOG[cfg['parallel_model']]['label']),
                'Whisper: '+('erst beim ersten Audioblock' if cfg['asr_on_demand'] else 'beim Start laden'),
                'Sprechertrennung: '+dict(resident='immer geladen',with_asr='zusammen mit Whisper',serial='seriell')[cfg['diarization_mode']],
                'Commander-Token: '+('aktiviert' if cfg['auth_enabled'] else 'ausgeschaltet')]
        lines += [GRADES[g]+': '+CATALOG[m]['label'] for g,m in cfg['quality_models'].items()]
        if cfg['remote_llm_url']: lines+=['LLM über anderen Commander: '+cfg['remote_llm_url']]
        if cfg['remote_diar_url']: lines+=['Sprechertrennung über '+cfg['remote_diar_url']]
        if local_role(cfg,'asr'):lines+=['Whisper-Modell: '+cfg['asr_model']]
    return dict(summary=lines,download_bytes=sum(f['bytes'] for m in cfg['selected_models'] for f in CATALOG[m]['files']) if cfg['mode']!='client' else 0)


class Installer:
    def __init__(self):
        self.support=support_dir(); self._hw=None
        self.lock=threading.Lock(); self.cancel=threading.Event()
        self.state=dict(running=False,done=False,error='',progress=0,message='',logs=[])
    @property
    def hw(self):
        if self._hw is None: self._hw=hardware(inspect_system())
        return self._hw
    def snapshot(self):
        with self.lock: return copy.deepcopy(self.state)
    def update(self, message=None, **values):
        with self.lock:
            if message and message!=self.state['message']:
                self.state['logs']=(self.state['logs']+[message])[-120:]; self.state['message']=message
            self.state.update(values)
    def start(self,cfg):
        validate(cfg,self.hw)
        with self.lock:
            if self.state['running']: raise ValueError('Die Installation läuft bereits.')
            self.state=dict(running=True,done=False,error='',progress=0,message='Installation vorbereiten',logs=[])
        self.cancel.clear()
        threading.Thread(target=self.run,args=(copy.deepcopy(cfg),),daemon=True).start()
    def run(self,cfg):
        self.operation('Install',cfg)
    def operation(self,action,cfg):
        tokens=[cfg.get(k) for k in SECRETS if cfg.get(k)]
        def redact(text):
            for token in tokens: text=text.replace(token,'[Token ausgelassen]')
            return text
        try:
            self.support.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='run-',dir=self.support) as temp:
                directory=Path(temp); request=directory/'request.json'; progress=directory/'progress.json'; result=directory/'result.json'
                request.write_text(json.dumps(cfg),encoding='utf-8'); request.chmod(0o600)
                with (directory/'stdout.log').open('wb') as out, (directory/'stderr.log').open('wb') as err:
                    p=subprocess.Popen(ps_args(action,'-InputPath',request,'-ProgressPath',progress,'-ResultPath',result),stdout=out,stderr=err,
                                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    cancel_sent=False
                    while p.poll() is None:
                        status=read_json(progress,{})
                        message=status.get('message')
                        percent=status.get('progress',0)
                        if status.get('engine_progress'):
                            engine=read_json(status['engine_progress'],{})
                            if engine.get('Message'): message=engine['Message']; percent=5+engine.get('Percent',0)*.82
                            # Only the existing engine's safe UAC-wait cancellation; never kill WSL during promotion.
                            if self.cancel.is_set() and engine.get('Phase') in ('admin_wait','admin_prompt') and status.get('cancel_path'):
                                Path(status['cancel_path']).write_text('cancel',encoding='ascii'); cancel_sent=True
                        if message: self.update(redact(message),progress=percent,can_cancel=bool(status.get('engine_progress') and engine.get('Phase')=='admin_wait'))
                        if self.cancel.is_set() and not cancel_sent:
                            self.update('Der laufende Systemschritt wird sicher abgeschlossen. Während einer Administrator-Wartepause ist ein Abbruch möglich.')
                        time.sleep(.25)
                outcome=read_json(result,{})
                if p.returncode or not outcome.get('done'):
                    message=outcome.get('error') or ('Installationshelfer unerwartet beendet (Exitcode %s). '%p.returncode)+(directory/'stderr.log').read_text(encoding='utf-8-sig',errors='replace')[-3000:]
                    raise ValueError(redact(message))
                self.update(outcome.get('message','Installation abgeschlossen'),**{k:v for k,v in outcome.items() if k!='message'},running=False,progress=100)
                self._hw=None
        except Exception as exc:
            self.update(redact(str(exc)),error=redact(str(exc)),running=False,done=False)


class Uninstaller(Installer):
    def __init__(self,support):
        super().__init__(); self.support=support
    def inspect(self):
        info=inspect_system()
        return dict(client=bool(info.get('client')),server=bool(info.get('previous')),models=bool(info.get('previous')),settings=True,unsafe=[])
    def start(self,cfg):
        keys={'remove_client','remove_server','remove_models','remove_settings'}
        if set(cfg)!=keys or any(type(v) is not bool for v in cfg.values()) or not (cfg['remove_client'] or cfg['remove_server']): raise ValueError('Komponenten zum Entfernen auswählen.')
        with self.lock:
            if self.state['running']: raise ValueError('Die Deinstallation läuft bereits.')
            self.state.update(running=True,done=False,error='',logs=[])
        threading.Thread(target=self.operation,args=('Uninstall',copy.deepcopy(cfg)),daemon=True).start()
