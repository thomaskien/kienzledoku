#!/usr/bin/env python3
"""Native Ubuntu entry point reusing the reviewed CUDA/worker installer engine."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

class ModelRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urllib.parse.urlsplit(newurl)
        if target.scheme!='https' or target.username or target.password:
            raise ValueError('Unsichere Modellweiterleitung.')
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        origin=urllib.parse.urlsplit(req.full_url)
        if redirected is not None and (origin.hostname,origin.port or 443)!=(target.hostname,target.port or 443):
            redirected.remove_header('Authorization')
        return redirected

def model_request(entry,token):
    url=entry['url']
    huggingface=url.startswith('https://huggingface.co/')
    sha=entry.get('sha256') or ''
    whisper_url=('https://openaipublic.azureedge.net/main/whisper/models/'
                 +sha+'/large-v3.pt')
    if not huggingface and not (entry.get('path')=='whisper/large-v3.pt' and url==whisper_url
                                and len(sha)==64 and all(c in '0123456789abcdef' for c in sha)):
        raise ValueError('Unerwartete Modellquelle.')
    headers={'User-Agent':'kienzledoku-installer/1.8.2'}
    if huggingface and token:headers['Authorization']='Bearer '+token
    return urllib.request.Request(url,headers=headers)

def download_progress(name,done,total,finished=False):
    amount = f'{done / 2**20:.1f} MiB'
    if total: amount += f' / {total / 2**20:.1f} MiB ({min(100,done*100/total):.0f} %)'
    print('\r'+name+': '+amount, end='\n' if finished or not sys.stdout.isatty() else '', flush=True)

def download(entry,target,token):
    from install_server import file_valid
    if file_valid(target,entry):
        print('Geprüft, wird wiederverwendet: '+entry['path'],flush=True)
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    request=model_request(entry,token)
    fd,name=tempfile.mkstemp(prefix='.'+target.name+'-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as output,urllib.request.build_opener(ModelRedirectHandler()).open(request,timeout=120) as source:
            total = int(entry.get('bytes') or getattr(source,'headers',{}).get('Content-Length') or 0)
            done = 0; last = 0.0
            while True:
                block = source.read(1024*1024)
                if not block: break
                output.write(block); done += len(block)
                now = time.monotonic()
                if now-last >= .5:
                    download_progress(entry['path'],done,total); last=now
            download_progress(entry['path'],done,total,finished=True)
        if not file_valid(Path(name),entry): raise ValueError('Modell-Prüfsumme stimmt nicht: '+entry['path'])
        os.chmod(name,0o644);os.replace(name,target)
    finally:
        if os.path.exists(name): os.unlink(name)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    for name in ('config','hf-token-file','token-file','remote-token-file','remote-diar-token-file'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()!=0 or os.environ.get('WSL_DISTRO_NAME'): raise ValueError('Nur über den nativen Ubuntu-Installer mit sudo starten.')
    cfg=json.loads(args.config.read_text());hf=args.hf_token_file.read_text().strip();token=args.token_file.read_text().strip();remote=args.remote_token_file.read_text().strip();remote_diar=args.remote_diar_token_file.read_text().strip()
    release=Path('/etc/os-release').read_text()
    sys.path.insert(0,str(args.source))
    from kienzledoku_linux_runtime import ubuntu_version
    ubuntu_version(release)
    source=args.source/'server-windows'
    target=Path('/opt/kienzledoku-server/installer')
    state=Path('/var/lib/kienzledoku-server');state.mkdir(parents=True,exist_ok=True)
    with (state/'install.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        sys.path.insert(0,str(source/'linux'))
        from managed_update import replace_tree
        with tempfile.TemporaryDirectory(prefix='kienzledoku-server-payload-') as directory:
            staged=Path(directory)/'installer'
            shutil.copytree(source/'linux',staged)
            for name in ('models.json','audio-files.json','audio-turbo-files.json','VERSION'): shutil.copy2(source/name,staged/name)
            shutil.copy2(source.parent/'LICENSE',staged/'LICENSE')
            replace_tree(staged,target,'install_server.py')
        sys.path.insert(0,str(target));import install_server as engine
        hw=engine.hardware(str(cfg['GpuIndex']));engine.validate_config(cfg,hw['vram_mib'])
        entries=[entry for key in cfg['Models'] for entry in engine.catalog()[key]['files']]
        entries+=engine.audio_files(cfg)
        for entry in entries:
            relative=Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts: raise ValueError('Ungültiger Modellpfad.')
            print('Modell prüfen / laden: '+entry['path'],flush=True)
            download(entry,engine.BASE/'models'/relative,hf)
        cfg['LinuxModelSource']=str(engine.BASE/'models')
        subprocess.run(['systemctl','stop',*engine.UNITS],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        engine.prepare_host();engine.import_models(cfg);engine.install_audio();engine.build_llama(hw)
        existing=engine.CONFIG/'token.env'
        if cfg['AuthEnabled']:
            if not token and existing.is_file(): token=existing.read_text().splitlines()[0].split('=',1)[1]
            token=token or secrets.token_urlsafe(32)
        else: token=''
        # Never put credentials in command arguments, JSON config, or progress output.
        engine.write(existing,'KIENZLEDOKU_COMMANDER_TOKEN='+token+'\n',0o600)
        engine.configure(cfg,hw)
        if remote: engine.write(existing,existing.read_text()+'KIENZLEDOKU_REMOTE_LLM_TOKEN='+remote+'\n',0o600)
        if remote_diar: engine.write(existing,existing.read_text()+'KIENZLEDOKU_REMOTE_DIAR_TOKEN='+remote_diar+'\n',0o600)
        runtime=engine.CONFIG/'installer.json';settings=json.loads(runtime.read_text());settings['host']=cfg['NativeBind']
        engine.write(runtime,json.dumps(settings,indent=2)+'\n')
        subprocess.run(['systemctl','enable',*engine.selected_units(cfg)],check=True)
        from systemd_start import start_unit
        start_unit(engine.UNITS[0],restart=True)
        subprocess.run([sys.executable,str(target/'control.py'),'start'],check=True)
        print('Commander installiert. Status: systemctl status kienzledoku-commander',flush=True)
if __name__=='__main__': main()
