"""Server catalogue with explicit serial and resident profiles, 32k / one slot."""
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
import argparse
import ipaddress
import json
import os
import signal
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

from kienzledoku_commander.config import Settings, Model, LABELS
from kienzledoku_commander.errors import BackendFailure
from kienzledoku_commander.runtime import Runtime
from kienzledoku_commander.scheduler import Commander
from kienzledoku_commander.api import API
from kienzledoku_commander.ownership import owner

@dataclass(frozen=True)
class SerialModel(Model):
    backend: str = 'llama.cpp'
    gpu_layers: int = 999
    run_config: str = ''

@dataclass(frozen=True)
class SerialSettings(Settings):
    profiles: dict = field(default_factory=dict)
    resident_quality: str | None = None

    @property
    def allowed(self):
        return tuple(self.profiles)

    @property
    def default(self):
        return self.default_quality

    @property
    def baseline_llm(self):
        if self.resident_quality is not None:
            return self.resident_quality or None
        return self.default if self.persistent(self.default) else None

    def persistent(self, quality):
        return self.profiles[quality].get('mode', 'serial') == 'parallel'

    def fallback(self, quality):
        if 'fallbacks' in self.profiles[quality]:
            return next((q for q in self.profiles[quality]['fallbacks'] if q != quality and q in self.allowed),None)
        # Larger selections may fall back only to an installed 9B model.
        order = ('sehr_gruendlich','gruendlich','basis')
        candidates = order[order.index(quality)+1:] if quality in order else ('gruendlich','basis')
        return next((q for q in candidates if q in self.allowed),None)

    def model(self, quality):
        quality = self.quality(quality)
        p = self.profiles[quality]
        return SerialModel(quality,p['path'],p['context'],p['slots'],p['kv'],
                           p['backend'],p['gpu_layers'],p.get('run_config',''))

    def validate(self):
        if type(self.tier) is not int or not 7 <= self.tier <= 128:
            raise ValueError('Ungültiger physischer VRAM-Wert.')
        # Preserve all original transport, queue, path and timeout checks.
        common = {f.name:getattr(self,f.name) for f in fields(Settings)}
        common.update(tier=8,default_quality='basis')
        Settings(**common).validate()
        ipaddress.ip_address(self.host)
        if not self.profiles or self.default not in self.profiles:
            raise ValueError('Standardmodell fehlt.')
        if self.resident_quality is not None:
            if not isinstance(self.resident_quality,str) or (self.resident_quality and self.resident_quality not in self.allowed):
                raise ValueError('Parallelmodell fehlt.')
            selected=[q for q in self.allowed if self.persistent(q)]
            if selected != ([self.resident_quality] if self.resident_quality else []):
                raise ValueError('Genau das ausgewählte Parallelmodell darf als parallel konfiguriert sein.')
        for quality,p in self.profiles.items():
            if not isinstance(quality,str) or not quality.replace('_','').isalnum():
                raise ValueError('Ungültige Modell-ID.')
            if not Path(p['path']).is_absolute() or p['context'] != 32768 or p['slots'] != 1:
                raise ValueError('Nur hinterlegte 32k/Ein-Slot-Profile verwenden.')
            if p['backend'] not in ('llama.cpp','strata') or p['kv'] not in ('q8_0','int8'):
                raise ValueError('Unbekanntes Backend oder KV-Format.')
            if type(p['gpu_layers']) is not int or not 0 <= p['gpu_layers'] <= 999:
                raise ValueError('Ungültiges GPU-Layer-Limit.')
            if p.get('mode','serial') not in ('serial','parallel'):
                raise ValueError('Ungültige Betriebsart.')
            minimum=p.get('parallel_vram_mib',{'basis':16128,'gruendlich':20224}.get(quality))
            if self.persistent(quality) and (type(minimum) is not int or minimum <= 0 or self.tier*1024 < minimum):
                raise ValueError('Kein freigegebenes Parallelprofil für dieses Modell/VRAM.')
            if 'fallbacks' in p and (not isinstance(p['fallbacks'],list) or any(not isinstance(q,str) for q in p['fallbacks'])):
                raise ValueError('Ungültige Modell-Fallbacks.')
            if p['backend']=='strata' and not Path(p.get('run_config','')).is_absolute():
                raise ValueError('Strata benötigt eine vorbereitete Startkonfiguration.')
            LABELS[quality] = p['label']
        return self

class SerialCommander(Commander):
    def _baseline(self):
        return {'asr':True,'diar':self.settings.baseline_llm is not None,
                'llm':self.settings.baseline_llm}

    def _desired(self,job):
        if job.role=='llm':
            if self.settings.persistent(job.quality):
                return {'asr':True,'diar':True,'llm':job.quality}
            return {'asr':False,'diar':False,'llm':job.quality}
        if job.role=='diar' and self.settings.baseline_llm is None:
            return {'asr':False,'diar':True,'llm':None}
        return self._baseline()

def model_command(settings,spec,quality):
    address=urlsplit(settings.llm_url)
    if spec.backend=='strata':
        return ['/opt/kienzledoku-strata/bin/strata','serve','--profile',spec.run_config,
                '--host',address.hostname,'--port',str(address.port),'--parallel','1','--offline','--quiet']
    return [settings.llama_binary,'--model',spec.path,'--alias',quality,
            '--host',address.hostname,'--port',str(address.port),
            '--parallel','1','--ctx-size',str(spec.context),'--n-gpu-layers',str(spec.gpu_layers),
            '--reasoning','off','--reasoning-format','deepseek',
            '--chat-template-kwargs','{"enable_thinking":false}',
            '--no-mmproj','--jinja','--cache-type-k',spec.kv,'--cache-type-v',spec.kv,
            '--flash-attn','on','--fit','off','--cont-batching','--top-k','40',
            '--top-p','0.95','--min-p','0.05','--repeat-penalty','1.0','--log-disable']

class SerialRuntime(Runtime):
    def infer(self,job):
        if job.role=='llm' and self.settings.model(job.quality).backend=='strata':
            request=dict(job.payload['llm'])
            request.update(chat_template_kwargs={'enable_thinking':False},reasoning_effort='none')
            job=replace(job,payload=dict(job.payload,llm=request))
        return super().infer(job)

    def load_llm(self,quality):
        if self.process is not None:
            if self.model==quality and self.process.poll() is None:
                return
            raise BackendFailure('Vorheriges LLM muss freigegeben sein.')
        spec=self.settings.model(quality)
        if not Path(spec.path).is_file():
            raise BackendFailure('Modelldatei fehlt.')
        address=urlsplit(self.settings.llm_url)
        try:
            with socket.create_connection((address.hostname,address.port),timeout=.2):
                raise BackendFailure('Interner LLM-Port bereits belegt.')
        except OSError:
            pass
        env=dict(os.environ,CUDA_VISIBLE_DEVICES=str(self.settings.gpu_index))
        try:
            self.process=subprocess.Popen(model_command(self.settings,spec,quality),env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            deadline=time.monotonic()+self.settings.load_timeout
            while time.monotonic()<deadline:
                if self.process.poll() is not None:
                    raise BackendFailure('LLM-Start fehlgeschlagen.')
                try:
                    health=self._http(self.settings.llm_url+'/health',timeout=2)
                    props=self._http(self.settings.llm_url+'/props',timeout=2)
                    if (health.get('status')=='ok' and
                        Path(props.get('model_path','')).resolve()==Path(spec.path).resolve() and
                        props.get('total_slots')==1 and
                        props.get('default_generation_settings',{}).get('n_ctx')==32768):
                        self.model=quality
                        return
                except BackendFailure:
                    pass
                time.sleep(.2)
            raise BackendFailure('LLM-Startzeit überschritten.')
        except (OSError,BackendFailure):
            self.stop_llm()
            raise BackendFailure('LLM konnte nicht bereitgestellt werden.') from None

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--check-config',action='store_true')
    args=parser.parse_args()
    settings=SerialSettings(**json.loads(args.config.read_text())).validate()
    if args.check_config:
        print(json.dumps({'default':settings.default,'allowed':settings.allowed,
                          'resident_quality':settings.baseline_llm,
                          'modes':{q:settings.profiles[q].get('mode','serial') for q in settings.allowed}}));return
    with owner(settings.control_dir):
        commander=SerialCommander(settings,SerialRuntime(settings))
        try:
            server=API((settings.host,settings.port),commander)
            def stop(*_):
                threading.Thread(target=server.shutdown,daemon=True).start()
            signal.signal(signal.SIGTERM,stop)
            signal.signal(signal.SIGINT,stop)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        finally:
            commander.close()

if __name__=='__main__':
    main()
