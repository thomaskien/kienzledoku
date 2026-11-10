#!/usr/bin/env python3
"""Synthetic WAV -> ASR -> diarization -> LLM, repeated return-to-ASR checks."""
from pathlib import Path
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from urllib.error import HTTPError

STATE=Path('/var/lib/kienzledoku-server')
CONFIG=Path('/etc/kienzledoku-server')
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def expected_baseline(cfg):
    resident=cfg.get('resident_quality')
    if resident is None:
        resident=cfg['default_quality'] if cfg['profiles'][cfg['default_quality']].get('mode','serial')=='parallel' else ''
    return {'asr':True,'diar':bool(resident),'llm':resident or None}

def main():
    cfg=json.loads((CONFIG/'installer.json').read_text())
    token=next(s.split('=',1)[1] for s in (CONFIG/'token.env').read_text().splitlines()
               if s.startswith('KIENZLEDOKU_COMMANDER_TOKEN='))
    host='127.0.0.1' if cfg['host']=='0.0.0.0' else cfg['host']
    base='http://'+host+':'+str(cfg['port'])
    wanted_baseline=expected_baseline(cfg)
    def get(path,body=None,content_type='application/json',final=False,auth=True):
        headers={'Content-Type':content_type}
        if auth:headers['Authorization']='Bearer '+token
        if final:headers['X-Kienzledoku-Recording-Finalized']='true'
        request=urllib.request.Request(base+path,data=body,headers=headers)
        with http.open(request,timeout=1500) as response:
            return json.load(response)
    def baseline():
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            try:
                s=get('/v1/runtime/status')
                if (s['asr_ready'] and s['loaded']==wanted_baseline
                    and not s['transition_running'] and not s['pending'] and not s['active'] and not s['last_error']):
                    return s
            except (OSError,ValueError):pass
            time.sleep(.5)
        raise AssertionError('ASR-Grundzustand wurde nicht erreicht.')
    def worker(name,directory):
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(10);s.connect(str(Path(directory)/name))
            s.sendall(b'{"operation":"status"}\n')
            result=json.loads(s.makefile('rb').readline(65537))
        assert result['ok'] is True
        return result['state']
    before=baseline()
    group=subprocess.check_output(['systemctl','show','kienzledoku-ai.slice','-p','ControlGroup','--value'],text=True).strip()
    cgroup=Path('/sys/fs/cgroup')/group.lstrip('/')
    memory_events_before=dict(line.split() for line in (cgroup/'memory.events').read_text().splitlines())
    original=worker('whisper.sock',cfg['control_dir'])
    profiles=get('/v1/runtime/profiles')
    assert all(p['context_per_slot']==32768 and p['slots']==1 for p in profiles['data'])
    try:get('/v1/runtime/status',auth=False)
    except HTTPError as exc:assert exc.code==401
    else:raise AssertionError('Tokenprüfung fehlt.')
    try:get('/v1/documentation/extract',json.dumps({'transcript':'Synthetischer Test.'}).encode())
    except HTTPError as exc:assert exc.code==409
    else:raise AssertionError('Abschlussbestätigung fehlt.')
    samples=[];done=threading.Event()
    def sample():
        while not done.is_set():
            try:
                text=subprocess.check_output(['nvidia-smi','-i',str(cfg['gpu_index']),
                    '--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'],text=True,timeout=5)
                used,total=[float(n.strip()) for n in text.strip().split(',')]
                samples.append({'time':time.time(),'used_mib':used,'total_mib':total})
            except (OSError,ValueError,subprocess.SubprocessError):pass
            done.wait(.2)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    result={'started':time.time(),'synthetic_only':True,'profiles':profiles,'baseline_before':before,'cycles':[]}
    try:
        with tempfile.TemporaryDirectory(prefix='kienzledoku-verify-') as temp:
            folder=Path(temp)
            subprocess.run(['espeak-ng','-v','de','-s','145','-w',str(folder/'source.wav'),
                'Seit drei Tagen besteht Husten. Fieber wird verneint. Die Lunge ist frei. '
                'Wir empfehlen ausreichend Flüssigkeit. Bei Verschlechterung erneute Vorstellung.'],check=True)
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(folder/'source.wav'),
                            '-ar','16000','-ac','1',str(folder/'test.wav')],check=True)
            wav=(folder/'test.wav').read_bytes()
            qualities=list(cfg['profiles'])
            for number,quality in enumerate(qualities*3):
                print('Prüfe vollständige Audiokette',number+1,flush=True)
                started=time.monotonic();boundary='kienzledoku-verify-boundary'
                multipart=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.wav"\r\n'
                           'Content-Type: audio/wav\r\n\r\n').encode()+wav+(
                           f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nde\r\n--{boundary}--\r\n').encode()
                asr=get('/v1/asr/final-block',multipart,'multipart/form-data; boundary='+boundary)
                assert isinstance(asr.get('text'),str) and asr['text'].strip()
                diar=get('/v1/diarize?num_speakers=1',wav,'audio/wav',True)
                assert diar['ok'] and isinstance(diar['segments'],list) and diar['segments']
                response=get('/v1/documentation/extract',json.dumps(dict(recording_finalized=True,
                    transcript=asr['text'],quality=quality)).encode())
                assert response['commander']['used_quality']==quality and not response['commander']['fallback_used']
                document=response['documentation']
                assert set(document)=={'anamnese','befund','therapie','prozedere'}
                assert all(isinstance(v,str) for v in document.values()) and any(document.values())
                restored=baseline();current=worker('whisper.sock',cfg['control_dir'])
                for key in ('pid','ct2_object_id','shared_object_id'):
                    assert current[key]==original[key],('Whisper-Objekt wurde ersetzt',key)
                assert current['ready'] and current['loaded'] and current['ct2_loaded']
                result['cycles'].append(dict(number=number+1,elapsed_s=time.monotonic()-started,
                    asr_characters=len(asr['text']),diar_segments=len(diar['segments']),
                    used_quality=response['commander']['used_quality'],
                    fallback_used=response['commander']['fallback_used'],restored=restored,
                    worker_object_ids_preserved=True))
            print('Prüfe langen Kontext und Rückkehr zur ASR.',flush=True)
            started=time.monotonic()
            long_text='Synthetischer Lasttest ohne klinische Angaben.\n'+('Test. '*12000)
            response=get('/v1/chat/completions',json.dumps(dict(
                model=cfg['default_quality'],recording_finalized=True,max_tokens=256,
                temperature=0,response_format={'type':'json_object'},
                messages=[{'role':'system','content':Path(cfg['prompt_path']).read_text()},
                          {'role':'user','content':long_text}])).encode())
            assert response['choices'][0]['finish_reason']=='stop'
            document=json.loads(response['choices'][0]['message']['content'])
            assert set(document)=={'anamnese','befund','therapie','prozedere'}
            assert response['usage']['prompt_tokens']>=20000
            baseline()
            current=worker('whisper.sock',cfg['control_dir'])
            for key in ('pid','ct2_object_id','shared_object_id'):
                assert current[key]==original[key]
            result['context_stress']=dict(input_tokens=response['usage']['prompt_tokens'],
                output_tokens=response['usage']['completion_tokens'],elapsed_s=time.monotonic()-started,
                asr_restored=True,worker_object_ids_preserved=True)
        memory_events_after=dict(line.split() for line in (cgroup/'memory.events').read_text().splitlines())
        assert int(memory_events_after['oom'])==int(memory_events_before['oom'])
        assert int(memory_events_after['oom_kill'])==int(memory_events_before['oom_kill'])
        assert int((cgroup/'memory.swap.current').read_text())==0
        result.update(ok=True,finished=time.time(),peak_vram_mib=max(s['used_mib'] for s in samples),
                      minimum_free_vram_mib=min(s['total_mib']-s['used_mib'] for s in samples),
                      samples=len(samples),sampling_interval_target_s=.2,
                      stack_cgroup_memory_peak_bytes=int((cgroup/'memory.peak').read_text()),
                      stack_cgroup_memory_max_bytes=int((cgroup/'memory.max').read_text()),
                      stack_cgroup_swap_bytes=int((cgroup/'memory.swap.current').read_text()),
                      memory_events_before=memory_events_before,memory_events_after=memory_events_after)
    except BaseException as exc:
        result.update(ok=False,error_type=type(exc).__name__,finished=time.time())
        raise
    finally:
        done.set();thread.join(timeout=6)
        STATE.mkdir(parents=True,exist_ok=True)
        path=STATE/'verification.json';path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
