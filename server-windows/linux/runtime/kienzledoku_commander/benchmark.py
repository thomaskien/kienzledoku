"""Explicit temporary benchmark control; no test loop, sampler or disk state."""
from pathlib import Path
import re
import json
import subprocess
import sys
import time
import uuid

from .errors import BackendFailure, Busy, Conflict, InvalidRequest

VERSION = '1.8.2'


def choices(settings, loaded=None):
    """Only configured/managed model paths, never a recursive disk search."""
    if settings.remote_llm_url or 'llm' not in settings.enabled_roles:return []
    candidates = list(settings.allowed)
    if hasattr(settings, 'profiles') and not settings.remote_llm_url:
        candidates += ['@'+mid if settings.quality_models else mid for mid in settings.profiles]
    else:
        candidates += ['@'+mid for mid in settings.benchmark_models]
    paths=list(dict.fromkeys(settings.model(q).path for q in candidates))
    try:
        present_by_path=json.loads(subprocess.check_output([sys.executable,'-I','-c',
            'import json,pathlib,sys;print(json.dumps({p:pathlib.Path(p).is_file() for p in json.loads(sys.argv[1])}))',
            json.dumps(paths)],timeout=2,stderr=subprocess.DEVNULL))
    except (OSError,ValueError,subprocess.SubprocessError):present_by_path={}
    entries = []
    by_identity = {}
    for quality in dict.fromkeys(candidates):
        spec = settings.model(quality)
        identity = (str(Path(spec.path)), spec.context, spec.slots, spec.kv, getattr(spec,'backend','llama.cpp'))
        if identity in by_identity:
            entry = by_identity[identity]
            if quality in settings.allowed:entry['aliases'].append(quality)
            entry['default'] |= quality == settings.default
            continue
        mid = spec.model_id or quality
        if any(e['id']==mid for e in entries):mid += '--'+quality.strip('@')
        options = settings.benchmark_models.get(spec.model_id,{})
        if hasattr(settings,'profiles'):
            profile = settings.profiles[settings.profile_id(quality)]
            minimum = profile.get('parallel_vram_mib')
            parallel = bool(minimum and settings.tier*1024 >= minimum)
        else:
            parallel = options.get('parallel_available', settings.persistent(quality))
        present = present_by_path.get(spec.path)
        match = re.search(r'(?:IQ|Q)\d[\w_-]*', Path(spec.path).stem, re.I)
        entry = dict(id=mid,model_id=spec.model_id,label=spec.label,gpu_layers=getattr(spec,'gpu_layers',None),
            aliases=[quality] if quality in settings.allowed else [],backend=identity[-1],
            quantization=options.get('quantization') or (match[0] if match else None),
            context=spec.context,context_per_slot=spec.context_per_slot,slots=spec.slots,kv=spec.kv,
            installed=present,available=bool(present) and 'llm' in settings.enabled_roles,
            reason=None if present else ('model_file_missing' if present is False else 'model_file_probe_unavailable'),default=quality==settings.default,
            loaded=bool(loaded and settings.runtime_quality(quality)==loaded),
            resident=bool(settings.baseline_llm and settings.runtime_quality(quality)==settings.runtime_quality(settings.baseline_llm)),
            parallel_available=bool(parallel),parallel_reason=None if parallel else 'no_approved_parallel_profile',
            filename=Path(spec.path).name,_quality=quality,_path=spec.path)
        entries.append(entry);by_identity[identity]=entry
    return entries


def inventory(settings, loaded=None):
    return [{k:v for k,v in e.items() if not k.startswith('_')} for e in choices(settings,loaded)]


def cache_metadata(settings):
    return dict(prompt_cache_requested=False,os_file_cache='unchanged_unknown',
                whisper_model_cache=__import__('os').environ.get('KIENZLEDOKU_AUDIO_CACHE','unknown'),
                note='Model reload does not prove a cold filesystem cache.')


class BenchmarkMixin:
    def _benchmark_init(self):
        self._benchmark = None
        self._last_benchmark = None
        self._last_benchmark_job = None

    def benchmark_begin(self, model_id, mode, lease_seconds=120):
        if mode not in ('serial','parallel') or type(lease_seconds) is not int or not 15 <= lease_seconds <= 300:
            raise InvalidRequest('Ungültiger Benchmarkmodus oder Lease.')
        with self._condition:
            if self._benchmark or self._closing or self._pending or self._active or self._transition or self._planned or self._awaiting_documentation or self._uncertain:
                raise Busy('Commander verarbeitet noch einen Vorgang.')
            entry = next((e for e in choices(self.settings,self._loaded['llm']) if e['id']==model_id),None)
            local_llm='llm' in self.settings.enabled_roles and not self.settings.remote_llm_url
            if local_llm:
                if entry is None or not entry['available']:raise InvalidRequest('Modell ist nicht installiert oder verfügbar.')
                if mode=='parallel' and not entry['parallel_available']:raise InvalidRequest('Kein freigegebener Parallelbetrieb für dieses Modell.')
            elif model_id is not None or mode!='serial':
                raise InvalidRequest('ASR-Commander benötigt model_id null und serial; LLM-Commander separat ansprechen.')
            self._last_error=None
            self._benchmark=dict(id=uuid.uuid4().hex,model_id=entry['id'] if entry else None,
                quality=entry['_quality'] if entry else None,mode=mode,lease_seconds=lease_seconds,
                expires=time.monotonic()+lease_seconds,state='active',restore=dict(self._baseline()),
                started=time.monotonic(),ending_at=None,seen=set(),error=None,model_changes=[])
            self._last_benchmark_job=None
            self._condition.notify_all()
            return self._benchmark_view(self._benchmark)

    def _benchmark_require(self, session_id):
        b=self._benchmark
        if not b or not isinstance(session_id,str) or session_id!=b['id']:
            raise InvalidRequest('Ungültige oder abgelaufene Benchmarksitzung.')
        return b

    def benchmark_keepalive(self, session_id):
        with self._condition:
            b=self._benchmark_require(session_id)
            if b['state']!='active' or time.monotonic()>=b['expires']:
                raise Busy('Benchmarksitzung wird beendet.')
            b['expires']=time.monotonic()+b['lease_seconds']
            return self._benchmark_view(b)

    def _benchmark_finish(self, reason):
        b=self._benchmark
        b['state']='restoring';b['ending_at']=time.monotonic();b['end_reason']=reason
        for job in list(self._pending):
            if job.benchmark_session==b['id']:
                self._pending.remove(job);self._complete(job,error=InvalidRequest('Benchmark beendet.'))
        self._awaiting_documentation=False
        self._planned=None;self._blocked.clear()
        self._condition.notify_all()

    def benchmark_end(self, session_id):
        with self._condition:
            if self._benchmark is None and self._last_benchmark and self._last_benchmark['id']==session_id:
                return self._benchmark_view(self._last_benchmark)
            b=self._benchmark_require(session_id)
            if b['state']=='active':self._benchmark_finish('requested')
            return self._benchmark_view(b)

    def _benchmark_tick(self):
        b=self._benchmark
        if not b:return
        now=time.monotonic()
        if b['state']=='active' and now>=b['expires']:self._benchmark_finish('lease_expired')
        if b['state']!='active' and not self._active and not self._pending and not self._transition:
            if self._loaded==b['restore'] and not self._uncertain:
                b['state']='completed';b['restored_at']=now
                self._last_benchmark=b;self._benchmark=None;self._last_benchmark_job=None
            elif self._last_error:
                b['error']='restoration_failed';b['state']='restoring'

    def _benchmark_view(self,b):
        return dict(id=b['id'],model_id=b['model_id'],mode=b['mode'],state=b['state'],
            lease_remaining_seconds=max(0,round(b['expires']-time.monotonic(),3)) if b['state']=='active' else 0,
            end_reason=b.get('end_reason'),restoration_error=b.get('error'),
            restoration_seconds=(round(b['restored_at']-b['ending_at'],4) if b.get('restored_at') and b.get('ending_at') else None),
            loaded=dict(self._loaded),settings_unchanged=True,
            diarization_mode=self.settings.diarization_mode,asr_on_demand=self.settings.asr_on_demand,
            cache=cache_metadata(self.settings),model_changes=list(b['model_changes']))

    def benchmark_status(self, session_id):
        with self._condition:
            b=self._benchmark if self._benchmark and self._benchmark['id']==session_id else self._last_benchmark
            if not b or b['id']!=session_id:raise InvalidRequest('Unbekannte Benchmarksitzung.')
            return self._benchmark_view(b)

    def _benchmark_target(self,job=None):
        b=self._benchmark
        if not b:return None
        if b['state']!='active':return dict(b['restore'])
        roles=set(self.settings.enabled_roles)
        if b['mode']=='parallel':
            target={'asr':'asr' in roles,'diar':False,'llm':b['quality']}
        elif job:
            target={'asr':job.role=='asr','diar':False,'llm':b['quality'] if job.role=='llm' else None}
        else:
            target={'asr':'asr' in roles and (not self.settings.asr_on_demand or bool(self._loaded['asr'])),'diar':False,'llm':None}
        # Keep the chosen diarization strategy; benchmark never invokes it.
        if self.settings.diarization_mode=='resident':target['diar']='diar' in roles
        elif self.settings.diarization_mode=='with_asr':target['diar']=target['asr'] and 'diar' in roles
        elif self.settings.diarization_mode is None:target['diar']=b['restore']['diar'] and (b['mode']=='parallel' or target['asr'])
        return self._runtime_target(target)

    def benchmark_job(self, session_id, request_id):
        with self._condition:
            job=self._remembered.get(request_id)
            if not job or job.benchmark_session!=session_id:raise InvalidRequest('Benchmarkauftrag nicht verfügbar.')
            return self._benchmark_job_view(job)

    def _benchmark_job_view(self,job):
        prepared=sum(c['seconds'] for c in job.model_changes if c['phase']=='prepare')
        returned=sum(c['seconds'] for c in job.model_changes if c['phase']=='return')
        end=job.completed_at
        return dict(request_id=job.id,session_id=job.benchmark_session,model_id=job.benchmark_model,
            role=job.role,state='failed' if job.failure_code else ('completed' if end is not None else ('running' if job.started_at else 'queued')),
            error=job.failure_code,clock='server_monotonic_seconds',submitted_at=job.submitted_at,
            inference_started_at=job.started_at,completed_at=end,
            queue_seconds=max(0,job.started_at-job.submitted_at-prepared) if job.started_at else None,
            model_preparation_seconds=round(prepared,6),
            inference_seconds=round(end-job.started_at,6) if end is not None and job.started_at else None,
            response_seconds=round(end-job.submitted_at,6) if end is not None else None,
            return_seconds=round(returned,6),return_complete=bool(end and not self._transition and self._loaded==self._baseline()),
            model_changes=list(job.model_changes),mode=job.benchmark_mode,ttft_seconds=None,ttft_reason='non_streaming_backend',
            backend=job.backend_metrics,cache=cache_metadata(self.settings),fallback_allowed=False)
