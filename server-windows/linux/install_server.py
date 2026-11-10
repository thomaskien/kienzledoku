#!/usr/bin/env python3
"""Server-only installation inside the installer's own Ubuntu 24.04 WSL2 instance."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import time
import traceback

from model_verification import VerificationCache

ROOT = Path(__file__).resolve().parent
VERSION = ((ROOT if (ROOT/'VERSION').is_file() else ROOT.parent)/'VERSION').read_text().strip()
BASE = Path('/opt/kienzledoku-server')
APP = BASE / 'runtime'
STATE = Path('/var/lib/kienzledoku-server')
CONFIG = Path('/etc/kienzledoku-server')
USER = 'kienzledoku-ai'
UNITS = ['kienzledoku-commander.service', 'kienzlefon-ai-asr-backend.service', 'kienzlefon-ai-diarization.service']
LLAMA_REVISION = 'aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3'
WHEEL_SHA = 'f11ff4c74f3efe11d09b50a08cfd6c33ed74fed4a397429d70254ada3feeeda6'
VERIFICATIONS = None
CURRENT_STEP = 'initializing'
CURRENT_COMMAND = []

def run(argv, **kwargs):
    global CURRENT_COMMAND
    CURRENT_COMMAND = list(map(str, argv))
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    return subprocess.run(list(map(str, argv)), check=True, **kwargs)

def capture(argv):
    global CURRENT_COMMAND
    CURRENT_COMMAND = list(map(str, argv))
    return subprocess.check_output(list(map(str, argv)), text=True).strip()

def write(path, value, mode=0o644):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.new')
    with temp.open('w', encoding='utf-8') as f:
        os.fchmod(f.fileno(), mode); f.write(value)
    temp.replace(path)

def save(name, value):
    write(STATE / name, json.dumps(value, indent=2) + '\n', 0o600)

def file_valid(path, entry):
    if VERIFICATIONS is not None:
        return VERIFICATIONS.check(path, entry)
    path = Path(path)
    if not path.is_file() or path.stat().st_size != entry['bytes']:
        return False
    sha = entry.get('sha256')
    h = hashlib.sha256() if sha else hashlib.sha1()
    if not sha:
        if not entry.get('git_blob_sha1'): raise ValueError('Prüfsumme fehlt.')
        h.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8*1024*1024), b''): h.update(block)
    return h.hexdigest() == (sha or entry['git_blob_sha1'])

def catalog():
    return json.loads((ROOT / 'models.json').read_text())

def validate_config(cfg, vram_mib):
    choices = catalog()
    if cfg['WslRamGiB'] not in (16,24,28,32): raise ValueError('Ungültiges RAM-Limit.')
    if cfg['DefaultModel'] not in cfg['Models']: raise ValueError('Standardmodell fehlt.')
    if cfg['AudioCache'] not in ('ram','disk'): raise ValueError('Ungültiger Audiocache.')
    if not cfg['Models'] or len(cfg['Models']) != len(set(cfg['Models'])): raise ValueError('Ungültige Modellauswahl.')
    if len({choices[key]['quality'] for key in cfg['Models']}) != len(cfg['Models']): raise ValueError('Modell-IDs müssen eindeutig sein.')
    if 'ParallelModel' in cfg:
        parallel=cfg['ParallelModel']
        if not isinstance(parallel,str) or (parallel and parallel not in cfg['Models']): raise ValueError('Parallelmodell fehlt.')
        configured=[key for key in cfg['Models'] if cfg['Profiles'][key]['Mode']=='parallel']
        if configured != ([parallel] if parallel else []): raise ValueError('Parallelkonfiguration stimmt nicht mit der Auswahl überein.')
    for key in cfg['Models']:
        item = choices[key]
        profile = cfg['Profiles'][key]
        if profile['Mode'] not in ('serial','parallel'): raise ValueError('Ungültige Betriebsart.')
        minimum = item['serial_vram_mib'] if profile['Mode']=='serial' else item['parallel_vram_mib']
        if minimum is None or vram_mib < minimum: raise ValueError('GPU reicht für ausgewähltes Profil nicht: '+key)
        if cfg['WslRamGiB']<item.get('ram_audio_min_wsl_gib',0) and cfg['AudioCache']!='disk':
            raise ValueError(item['label']+' benötigt bei diesem WSL-RAM-Limit den Whisper-SSD-Sparmodus.')
    return cfg

def hardware(gpu):
    smi = shutil.which('nvidia-smi') or '/usr/lib/wsl/lib/nvidia-smi'
    raw = capture([smi,'-i',gpu,'--query-gpu=name,memory.total,compute_cap,driver_version','--format=csv,noheader,nounits'])
    name, size, cc, driver = [s.strip() for s in raw.split(',')]
    if float(cc)<7.5: raise ValueError('CUDA 13 benötigt für diesen Installer Compute Capability 7.5 oder neuer (RTX 20-Serie oder neuer).')
    memory=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))*1024
    return dict(name=name,vram_mib=int(size),compute_capability=cc,driver=driver,ram_bytes=memory)

def check_memory(cfg,hw):
    if hw['ram_bytes'] < (cfg['WslRamGiB']-1)*1024**3:
        raise ValueError('Das gewählte WSL-RAM-Limit ist noch nicht wirksam. Alle WSL-Instanzen schließen und Windows neu starten; danach fortsetzen.')

def prepare_host():
    env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',PATH='/usr/lib/wsl/lib:/usr/local/cuda/bin:'+os.environ['PATH'])
    run(['apt-get','update'],env=env)
    run(['apt-get','-o','DPkg::Lock::Timeout=300','install','-y','build-essential','cmake','ninja-build','git',
         'curl','ca-certificates','python3','python3-venv','python3-pip','python3-dev','ffmpeg','sudo',
         'pkg-config','libssl-dev','libcurl4-openssl-dev','espeak-ng'],env=env)
    if not Path('/usr/local/cuda/bin/nvcc').exists():
        keyring=STATE/'cuda-keyring.deb'
        run(['curl','--fail','--location','--retry','4','--output',keyring,
             'https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb'])
        run(['dpkg','-i',keyring])
        run(['apt-get','update'],env=env)
        # Toolkit only. Linux display drivers break CUDA's WSL driver bridge.
        run(['apt-get','-o','DPkg::Lock::Timeout=300','install','-y','cuda-toolkit-13-0'],env=env)
    try: pwd.getpwnam(USER)
    except KeyError:
        run(['useradd','--system','--user-group','--create-home','--home-dir','/var/lib/kienzledoku-ai',
             '--shell','/usr/sbin/nologin',USER])

def import_models(cfg):
    source=Path(cfg['LinuxModelSource'])
    entries=[f for key in cfg['Models'] for f in catalog()[key]['files']]
    entries+=json.loads((ROOT/'audio-files.json').read_text())
    for entry in entries:
        relative=Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Ungültiger Modellpfad.')
        target=BASE/'models'/relative
        if file_valid(target,entry): continue
        origin=Path(cfg.get('LinuxModelSources',{}).get(entry['path'],str(source/relative)))
        # Verify the new destination after copying; a second full read of the
        # source adds no integrity guarantee. Never promote an unchecked copy
        # when checksum verification is enabled.
        if not origin.is_file() or origin.stat().st_size!=entry['bytes']:
            raise ValueError('Modellquelle fehlt oder Dateigröße falsch: '+str(relative))
        print('Importiere '+str(relative),flush=True)
        target.parent.mkdir(parents=True,exist_ok=True)
        stage=target.with_name(target.name+'.part')
        if VERIFICATIONS is not None: VERIFICATIONS.forget(stage)
        shutil.copyfile(origin,stage)
        if VERIFICATIONS is not None:
            VERIFICATIONS.commit(stage,target,entry)
        else:
            if not file_valid(stage,entry): raise ValueError('Prüfsumme nach Kopieren falsch: '+str(relative))
            stage.replace(target)
    # Reconstruct an ordinary, pinned HF cache: no authenticated downloads at service start.
    for entry in entries:
        if not entry['path'].startswith('pyannote/'): continue
        hub=BASE/'models/huggingface/hub'/('models--'+entry['repository'].replace('/','--'))
        target=hub/'snapshots'/entry['revision']/entry['filename']
        target.parent.mkdir(parents=True,exist_ok=True)
        target.unlink(missing_ok=True)
        target.symlink_to(BASE/'models'/entry['path'])
        write(hub/'refs/main',entry['revision']+'\n')
    # Avoid changing ctime on every repair, invalidating all saved model proofs.
    run(['chown','-R','--from=root',USER+':'+USER,BASE/'models'])
    if VERIFICATIONS is not None and VERIFICATIONS.enabled:
        # Initial ownership changes legitimately alter ctime after verification.
        # Carry forward only the same inode, size and mtime after our own chown.
        for entry in entries:
            target=BASE/'models'/entry['path']
            after=VERIFICATIONS.fingerprint(target)
            old=VERIFICATIONS.entries.get(after['path'],{})
            before=old.get('fingerprint',{})
            if all(before.get(k)==after[k] for k in ('device','inode','bytes','mtime_ns')):
                VERIFICATIONS.remember(after,VERIFICATIONS.checksum(entry))
    if cfg.get('ModelImportId'):
        save('model-import.json',dict(run_id=cfg['ModelImportId'],verify_model_files=cfg.get('VerifyModelFiles',True),files=[dict(path=e['path'],bytes=e['bytes']) for e in entries]))

def install_audio():
    env=dict(os.environ,HF_HUB_DISABLE_XET='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    for role,cuda in [('asr','cu129'),('diarization','cu130')]:
        venv=BASE/'python'/(role+'-venv'); py=venv/'bin/python'
        # Dependency set 1.0 is unchanged; product releases reuse this cache.
        stamp=STATE/(role+'-packages-1.0.json')
        if not stamp.exists():
            if not py.exists(): run([sys.executable,'-m','venv',venv])
            run([py,'-m','pip','install','--upgrade','pip'],env=env)
            run([py,'-m','pip','install','--index-url','https://download.pytorch.org/whl/'+cuda,
                 'torch==2.11.0','torchaudio==2.11.0'],env=env)
            if role=='asr':
                wheels=STATE/'wheels';wheels.mkdir(exist_ok=True)
                run([py,'-m','pip','download','--no-deps','--only-binary=:all:','--dest',wheels,'whisperlivekit==0.2.24'],env=env)
                wheel=next(wheels.glob('whisperlivekit-0.2.24-*.whl'))
                if hashlib.sha256(wheel.read_bytes()).hexdigest()!=WHEEL_SHA: raise ValueError('WhisperLiveKit-Wheel stimmt nicht.')
                run([py,'-m','pip','install',wheel,'faster-whisper==1.2.1','ctranslate2==4.8.1'],env=env)
            else:
                run([py,'-m','pip','install','pyannote.audio==4.0.7'],env=env)
            run([py,'-c','import torch; assert torch.cuda.is_available(), "CUDA fehlt"; print(torch.cuda.get_device_name(0))'])
            save(stamp.name,{'version':'1.0','cuda':cuda,'time':time.time()})
    shutil.copytree(ROOT/'runtime',APP,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    scripts=BASE/'scripts';scripts.mkdir(exist_ok=True)
    diar=scripts/'diarization_server.py'
    # Preserve an already verified worker hook on a repair run.
    if not (STATE/'worker-backup/manifest.json').exists(): shutil.copyfile(ROOT/'vendor/diarization_server.py',diar)
    final_script=(ROOT/'vendor/final-block.sh').read_text().replace('/opt/kienzlefon-ai-v2',str(BASE))
    write(STATE/'patch-final-block.sh',final_script,0o700)
    run(['bash',STATE/'patch-final-block.sh'],env=dict(os.environ,KIENZLEDOKU_NO_START='1'))
    target=Path(capture([BASE/'python/asr-venv/bin/python','-c',
        'import whisperlivekit,pathlib; print(pathlib.Path(whisperlivekit.__file__).parent/"basic_server.py")']))
    run([sys.executable,'-m','kienzledoku_commander.patch_workers','--whisper',target,'--diar',diar,
         '--backup',STATE/'worker-backup'],env=dict(os.environ,PYTHONPATH=str(APP)))

def build_llama(hw):
    source=BASE/'src/llama.cpp'; build=source/'build-kienzledoku'
    stamp=STATE/'llama-build.json'
    identity={'revision':LLAMA_REVISION,'compute_capability':hw['compute_capability']}
    if stamp.exists() and json.loads(stamp.read_text())==identity and (build/'bin/llama-server').is_file(): return
    source.parent.mkdir(parents=True,exist_ok=True)
    if not (source/'.git').exists():
        run(['git','init',source]);run(['git','-C',source,'remote','add','origin','https://github.com/ggml-org/llama.cpp.git'])
    run(['git','-C',source,'fetch','--depth','1','origin',LLAMA_REVISION]);run(['git','-C',source,'checkout','--detach','FETCH_HEAD'])
    env=dict(os.environ,PATH='/usr/local/cuda/bin:'+os.environ['PATH'])
    run(['cmake','-S',source,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DGGML_CUDA=ON',
         '-DGGML_NATIVE=OFF','-DLLAMA_OPENSSL=OFF','-DLLAMA_BUILD_UI=OFF','-DLLAMA_BUILD_NUMBER=9637',
         '-DCMAKE_CUDA_ARCHITECTURES='+hw['compute_capability'].replace('.',''),
         '-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF','-DLLAMA_BUILD_TOOLS=ON'],env=env)
    run(['cmake','--build',build,'--target','llama-server','llama-cli','-j','2'],env=env)
    (BASE/'bin').mkdir(exist_ok=True)
    for name in ('llama-server','llama-cli'):
        link=BASE/'bin'/name;link.unlink(missing_ok=True);link.symlink_to(build/'bin'/name)
    run([BASE/'bin/llama-cli','--list-devices'],env=env); save('llama-build.json',identity)

def runtime_settings(cfg,hw):
    profiles={}
    for key in cfg['Models']:
        item=catalog()[key]
        profiles[item['quality']]=dict(item['profile'],path=str(BASE/'models'/item['files'][0]['path']),
                                      label=item['label'],mode=cfg['Profiles'][key]['Mode'],
                                      parallel_vram_mib=item['parallel_vram_mib'],fallbacks=item.get('fallbacks',
                                      {'basis':[],'gruendlich':['basis'],'sehr_gruendlich':['gruendlich','basis']}.get(item['quality'],[])))
    server=dict(tier=round(hw['vram_mib']/1024),host='127.0.0.1',port=8185,gpu_index=cfg['GpuIndex'],
                default_quality=catalog()[cfg['DefaultModel']]['quality'],llama_binary=str(BASE/'bin/llama-server'),
                profiles=profiles,prompt_path=str(APP/'prompt_documentation.txt'),control_dir='/run/kienzledoku-commander',
                diar_control_dir='/run/kienzledoku-commander-diar',max_pending=4,max_remembered=8,max_payload_mib=64,
                load_timeout=600,backend_timeout=1200,queue_timeout=1800)
    if 'ParallelModel' in cfg:
        server['resident_quality']=catalog()[cfg['ParallelModel']]['quality'] if cfg['ParallelModel'] else ''
    return server

def configure(cfg,hw):
    CONFIG.mkdir(parents=True,exist_ok=True)
    token_file=CONFIG/'token.env'
    if not token_file.exists(): write(token_file,'KIENZLEDOKU_COMMANDER_TOKEN='+secrets.token_urlsafe(32)+'\n',0o600)
    server=runtime_settings(cfg,hw)
    write(CONFIG/'installer.json',json.dumps(server,indent=2)+'\n')
    save('windows-config.json',cfg)
    # Reserve 3 GiB of the WSL limit for the Linux kernel and shared runtime code.
    cap=cfg['WslRamGiB']-3
    write('/etc/systemd/system/kienzledoku-ai.slice',f'[Unit]\nDescription=Kienzledoku server memory budget\n[Slice]\nMemoryHigh={cap-1}G\nMemoryMax={cap}G\nMemorySwapMax=0\n')
    shared=f'''User={USER}
Group={USER}
Slice=kienzledoku-ai.slice
Environment=PYTHONPATH={APP}
Environment=PYTHONUNBUFFERED=1
Environment=CUDA_VISIBLE_DEVICES={cfg['GpuIndex']}
Environment=HF_HOME={BASE}/models/huggingface
Environment=HF_HUB_OFFLINE=1
Environment=HF_HUB_DISABLE_XET=1
Environment=KIENZLEDOKU_SERIAL_BOOT=1
Environment=KIENZLEDOKU_AUDIO_CACHE={cfg['AudioCache']}
Restart=on-failure
RestartSec=10
TimeoutStartSec=600
TimeoutStopSec=120
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=null
StandardError=journal
'''
    diar=f'''[Unit]
Description=Kienzledoku pyannote worker
After=network.target
[Service]
{shared}WorkingDirectory={BASE}
Environment=DIARIZATION_HOST=127.0.0.1
Environment=DIARIZATION_PORT=8183
Environment=DIARIZATION_DEVICE=cuda:0
Environment=PYANNOTE_MODEL=pyannote/speaker-diarization-community-1
Environment=KIENZLEDOKU_COMMANDER_CONTROL_DIR=/run/kienzledoku-commander-diar
RuntimeDirectory=kienzledoku-commander-diar
RuntimeDirectoryMode=0700
ExecStart={BASE}/python/diarization-venv/bin/python {BASE}/scripts/diarization_server.py
ExecStartPost=/usr/bin/python3 {APP}/wait_worker.py /run/kienzledoku-commander-diar/diarization.sock
'''
    asr=f'''[Unit]
Description=Kienzledoku Whisper worker
After={UNITS[2]}
Requires={UNITS[2]}
[Service]
{shared}Environment=KIENZLEDOKU_SERIAL_ASR_CPU_STAGE=1
Environment=KIENZLEDOKU_COMMANDER_CONTROL_DIR=/run/kienzledoku-commander
RuntimeDirectory=kienzledoku-commander
RuntimeDirectoryMode=0700
ExecStart={BASE}/python/asr-venv/bin/wlk --backend faster-whisper --backend-policy simulstreaming --language de --host 127.0.0.1 --port 8179 --frame-threshold 25 --pcm-input --model-path {BASE}/models/whisper
ExecStartPost=/usr/bin/python3 {APP}/wait_worker.py /run/kienzledoku-commander/whisper.sock
'''
    commander=f'''[Unit]
Description=kienzledoku Server {VERSION}
After={UNITS[1]} {UNITS[2]}
Requires={UNITS[1]} {UNITS[2]}
[Service]
{shared}WorkingDirectory={APP}
EnvironmentFile={token_file}
ExecStart=/usr/bin/python3 {APP}/serial_server.py --config {CONFIG}/installer.json
'''
    for name,unit in zip(UNITS,[commander,asr,diar]): write('/etc/systemd/system/'+name,unit)
    run(['systemctl','daemon-reload'])
    env=dict(os.environ,PYTHONPATH=str(APP))
    env['KIENZLEDOKU_COMMANDER_TOKEN']=token_file.read_text().strip().split('=',1)[1]
    run([sys.executable,APP/'serial_server.py','--config',CONFIG/'installer.json','--check-config'],env=env)
    save('installed.json',{'version':VERSION,'models':cfg['Models'],'default':cfg['DefaultModel'],'parallel_model':cfg.get('ParallelModel'),
                           'hardware':hw,'time':time.time(),'verified':False,'model_checksums_verified':cfg.get('VerifyModelFiles',True)})

def main():
    global VERIFICATIONS, CURRENT_STEP
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();cfg=json.loads(args.config.read_text(encoding='utf-8-sig'))
    if os.geteuid()!=0 or os.environ.get('WSL_DISTRO_NAME')!='kienzledoku-server':
        raise ValueError('Nur als root in der eigenen WSL-Instanz kienzledoku-server ausführen.')
    release=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID','').strip('"')!='ubuntu' or release.get('VERSION_ID','').strip('"')!='24.04':
        raise ValueError('Ubuntu 24.04 erforderlich.')
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'install.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        hw=hardware(cfg['GpuIndex']);validate_config(cfg,hw['vram_mib']);check_memory(cfg,hw)
        subprocess.run(['systemctl','stop',*UNITS],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        VERIFICATIONS=VerificationCache(STATE/'model-verifications.json',
            force=cfg.get('ForceModelVerification',False) and not cfg.get('ModelPreflightVerified',False),
            enabled=cfg.get('VerifyModelFiles',True))
        steps=[('Systempakete und CUDA-Toolkit',prepare_host,()),('Modelle übernehmen',import_models,(cfg,)),
               ('Whisper und pyannote vorbereiten',install_audio,()),('llama.cpp bereitstellen und kompilieren',build_llama,(hw,)),
               ('Server konfigurieren',configure,(cfg,hw))]
        for name,action,arguments in steps:
            CURRENT_STEP=name
            save('progress.json',{'state':'installing','version':VERSION,'step':name})
            print('Installationsschritt: '+name,flush=True)
            action(*arguments)
        # Windows owns start/autostart; no independent Linux boot entry point.
        subprocess.run(['systemctl','disable',*UNITS],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        save('progress.json',{'state':'installed','version':VERSION,'verified':False})
        print('SERVER_INSTALL_OK',flush=True)

def report_failure(exc):
    detail={'state':'error','version':VERSION,'step':CURRENT_STEP,'command':CURRENT_COMMAND,
            'exception':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    try: save('installation-error.json',detail)
    except OSError: pass
    print('Serverinstallation fehlgeschlagen im Schritt '+CURRENT_STEP+': '+str(exc),file=sys.stderr,flush=True)
    traceback.print_exc()

if __name__=='__main__':
    try: main()
    except Exception as exc:
        report_failure(exc);sys.exit(1)
