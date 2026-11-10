#!/usr/bin/env python3
"""Own-instance start, stop, status, verification and safe model removal."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from install_server import BASE,STATE,CONFIG,UNITS,hardware,validate_config,check_memory

def execute(action):
    if os.geteuid()!=0 or os.environ.get('WSL_DISTRO_NAME')!='kienzledoku-server':
        raise ValueError('Nur als root in kienzledoku-server ausführen.')
    if action=='start':
        cfg=json.loads((STATE/'windows-config.json').read_text())
        hw=hardware(cfg['GpuIndex']);validate_config(cfg,hw['vram_mib']);check_memory(cfg,hw)
        identity=json.loads((STATE/'llama-build.json').read_text())
        if identity['compute_capability']!=hw['compute_capability']:
            raise ValueError('GPU-Architektur geändert. Installer zur Reparatur erneut ausführen.')
        subprocess.run(['systemctl','start',UNITS[0]],check=True)
        token=(CONFIG/'token.env').read_text().strip().split('=',1)[1]
        request=urllib.request.Request('http://127.0.0.1:8185/v1/runtime/status',headers={'Authorization':'Bearer '+token})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            try:
                with opener.open(request,timeout=5) as response: status=json.load(response)
                if status['asr_ready'] and not status['transition_running'] and not status['last_error']:
                    print('SERVER_READY');return
            except (OSError,ValueError): pass
            time.sleep(.5)
        raise ValueError('Server wird nicht bereit. Linux-Dienstprotokoll prüfen.')
    elif action=='stop':
        subprocess.run(['systemctl','stop',*UNITS],check=True)
        for unit in UNITS:
            if subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0:
                raise ValueError('Dienst blieb aktiv: '+unit)
        print('SERVER_STOPPED')
    elif action=='status':
        subprocess.run(['systemctl','--no-pager','--full','status',*UNITS],check=False)
    elif action=='state':
        print(json.dumps({'active':subprocess.run(['systemctl','is-active','--quiet',UNITS[0]]).returncode==0}))
    elif action=='token':
        # Called only by the local per-user Windows controller; never part of logs.
        print((CONFIG/'token.env').read_text().strip().split('=',1)[1])
    elif action=='verify':
        subprocess.run([sys.executable,ROOT/'verify.py'],check=True)
        p=STATE/'installed.json';state=json.loads(p.read_text());state['verified']=True
        p.write_text(json.dumps(state,indent=2)+'\n')
    elif action=='remove-models':
        execute('stop')
        target=BASE/'models'
        if target.is_symlink(): raise ValueError('Unerwarteter Modellpfad.')
        if target.exists(): shutil.rmtree(target)
        print('Eigene Laufzeitmodelle entfernt. Downloadquellen bleiben erhalten.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','status','state','token','verify','remove-models'])
    args=parser.parse_args()
    try: execute(args.action)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
