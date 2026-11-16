#!/usr/bin/env python3
"""Text installer for Ubuntu 24.04: client, local Commander, or both."""
import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import kienzledoku_config as client_config
from kienzledoku_document import DOCUMENT_LABELS
from kienzledoku_product_key import production_build
from installer.linux_uninstall import Uninstaller
VERSION='1.8'
GRADES=('basis','gruendlich','sehr_gruendlich')
GRADE_LABELS={'basis':'Basis','gruendlich':'Gründlich','sehr_gruendlich':'Sehr gründlich'}
DIARIZATION_MODES={'resident':'Immer geladen','with_asr':'Zusammen mit Whisper','serial':'Seriell – nach Whisper, vor dem LLM'}
DEFAULTS=dict(basis='qwen4-q4',gruendlich='gemma12-q8',sehr_gruendlich='27b-q4')
FIELDS=('anamnese','befund','ekg','sonografie','therapie','prozedere','notiz')
DOCS='https://github.com/thomaskien/kienzledoku#t2med-einrichten-und-verwenden'
SERVER_STATE=Path('/var/lib/kienzledoku-server/windows-config.json')
SERVER_TOKENS=Path('/etc/kienzledoku-server/token.env')

def read_server_file(path):
    if not path.exists(): return ''
    try:
        return path.read_text()
    except PermissionError:
        # The server installer already requires sudo; capture its private state
        # without exposing the contents in terminal output or command arguments.
        return subprocess.check_output(['sudo',sys.executable,'-c',
            'from pathlib import Path;import sys;print(Path(sys.argv[1]).read_text())',str(path)],text=True)

def previous_server_settings():
    raw=read_server_file(SERVER_STATE)
    if not raw:return {}
    try:
        value=json.loads(raw)
        if not isinstance(value,dict): raise ValueError()
        return value
    except ValueError:
        raise ValueError('Vorhandene Servereinstellungen konnten nicht gelesen werden; sie werden nicht durch Standardwerte ersetzt.') from None

def previous_server_tokens():
    tokens={}
    for line in read_server_file(SERVER_TOKENS).splitlines():
        key,separator,value=line.partition('=')
        if separator and key in ('KIENZLEDOKU_COMMANDER_TOKEN','KIENZLEDOKU_REMOTE_LLM_TOKEN'):
            if len(value)>4096 or any(c.isspace() for c in value):
                raise ValueError('Vorhandene Token-Datei enthält eine ungültige Einstellung.')
            tokens[key]=value
    return tokens

def token_answer(label,existing='',optional=False):
    if existing:print('Vorhandener '+label+' erkannt (Wert bleibt verborgen).')
    hint='Enter = übernehmen' if existing else 'leer = optional' if optional else 'leer = automatisch erzeugen'
    value=getpass.getpass(label+' (unsichtbar; '+hint+('; - = entfernen' if optional and existing else '')+'): ')
    if value=='-' and optional:return ''
    return value or existing

def operating_answers(catalog,selected,vram,previous):
    parallel_choices=[key for key in selected if catalog[key].get('parallel_vram_mib') is not None
                      and catalog[key]['parallel_vram_mib']<=vram]
    saved=previous.get('ParallelModel')
    if saved is None:
        saved=next((key for key,profile in previous.get('Profiles',{}).items() if profile.get('Mode')=='parallel'),'')
    parallel=''
    if parallel_choices:
        print('\nModellbetrieb: seriell spart Grafikspeicher; parallel hält ein ausgewähltes LLM neben Whisper bereit.')
        default='parallel' if saved in parallel_choices else 'seriell'
        if saved and saved not in parallel_choices:
            print('Das bisherige Parallelmodell ist für diese Auswahl/GPU nicht verfügbar. Vorgabe: seriell.')
        while True:
            mode=ask('Modellbetrieb: seriell / parallel',default).lower()
            if mode in ('seriell','serial','parallel'): break
            print('Bitte seriell oder parallel wählen.')
        if mode=='parallel':
            if len(parallel_choices)==1:
                parallel=parallel_choices[0]
                print('Parallel vorgehaltenes Modell: '+catalog[parallel]['label'])
            else:
                for key in parallel_choices: print(key+' — '+catalog[key]['label'])
                while True:
                    parallel=ask('Parallel vorgehaltenes Modell',saved if saved in parallel_choices else parallel_choices[0])
                    if parallel in parallel_choices: break
                    print('Bitte ein für diese GPU freigegebenes Modell aus der Liste wählen.')
    else:
        print('\nModellbetrieb: seriell. Für die gewählten Modelle ist auf dieser GPU kein Parallelprofil freigegeben.')
        for key in selected:
            minimum=catalog[key].get('parallel_vram_mib')
            print(catalog[key]['label']+(': kein Parallelprofil hinterlegt.' if minimum is None else
                ': Parallelprofil benötigt '+str(minimum)+' MiB; erkannt wurden '+str(vram)+' MiB.'))
    print('Whisper auf Abruf: Laden beim ersten Audioblock; nach dem Entladen nicht erneut vorladen.')
    print('Zusammen mit seriellem Modellbetrieb ist dies der verschärft serielle Modus.')
    on_demand=yes('Whisper erst bei Bedarf laden (verschärft seriell)?',previous.get('AsrOnDemand',True))
    return parallel,on_demand

def ask(label,default=''):
    value=input(label+(' ['+str(default)+']' if default!='' else '')+': ').strip()
    return value or str(default)

def yes(label,default=False):
    while True:
        v=ask(label+' (j/n)','j' if default else 'n').lower()
        if v in ('j','ja','y','yes'): return True
        if v in ('n','nein','no'): return False

def private_write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f: f.write(value)
    os.chmod(path,0o600)

def prompt_edit(value):
    while True:
        print('\nCommander-Prompt:\n'+value)
        action=ask('Prompt: übernehmen / bearbeiten / standard','übernehmen').lower()
        if action in ('übernehmen','uebernehmen'): return value
        if action=='standard': value=(ROOT/'prompt_documentation.txt').read_text();continue
        if action=='bearbeiten':
            with tempfile.TemporaryDirectory(prefix='kienzledoku-prompt-') as temp:
                p=Path(temp)/'prompt.txt';private_write(p,value)
                subprocess.run(shlex.split(os.environ.get('EDITOR','nano'))+[str(p)],check=True)
                changed=p.read_text()
                if changed.strip() and len(changed)<200000: value=changed
                else: print('Der Prompt darf nicht leer oder größer als 200000 Zeichen sein.')

def server_answers():
    previous=previous_server_settings()
    catalog=json.loads((ROOT/'server-windows/models.json').read_text())
    print('\nLokaler Server: NVIDIA RTX 20 oder neuer, mindestens 8 GiB VRAM.')
    rows=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.total','--format=csv,noheader,nounits'],text=True).strip().splitlines()
    print('\n'.join(rows))
    indices=[int(row.split(',')[0]) for row in rows]
    saved_gpu=previous.get('GpuIndex')
    gpu=int(ask('GPU-Index',saved_gpu if saved_gpu in indices else indices[0]))
    vram=int(next(row.rsplit(',',1)[1] for row in rows if int(row.split(',')[0])==gpu))
    eligible={k:v for k,v in catalog.items() if v['serial_vram_mib']<=vram}
    if not eligible: raise ValueError('Kein freigegebenes Modell für diese GPU.')
    for key,m in eligible.items(): print(key+' — '+m['label']+' ('+GRADE_LABELS[m['grade']]+')')
    previous_models=previous.get('Models')
    selected_default=','.join(k for k in (previous_models if previous_models else DEFAULTS.values()) if k in eligible)
    if not selected_default:selected_default=','.join(k for k in DEFAULTS.values() if k in eligible)
    while True:
        selected=[k.strip() for k in ask('Zu installierende Modelle, durch Komma getrennt',selected_default).split(',')]
        if selected and len(set(selected))==len(selected) and all(k in eligible for k in selected): break
        print('Bitte eindeutige Modell-IDs aus der Liste wählen.')
    print('\nModelle den Verarbeitungsstufen zuordnen:')
    print('Enter übernimmt das angezeigte Modell. Weitere installierte Modelle bleiben zum späteren Umschalten verfügbar.')
    mapping={}
    for grade in GRADES:
        label=GRADE_LABELS[grade]
        options=[k for k in selected if catalog[k]['grade']==grade]
        if not options:
            print(label+': nicht verfügbar — kein Modell dieser Stufe ausgewählt.')
            continue
        for key in options:print('  '+label+': '+key+' — '+catalog[key]['label'])
        while True:
            saved=previous.get('QualityModels',{}).get(grade,DEFAULTS[grade])
            chosen=ask(label+' — aktives Modell ('+', '.join(options)+')',saved if saved in options else options[0])
            if chosen in options: mapping[grade]=chosen;break
            print('Bitte eine der oben für '+label+' angezeigten Modell-IDs wählen.')
    parallel,on_demand=operating_answers(catalog,selected,vram,previous)
    old_fields=previous.get('EnabledFields',('anamnese','befund','therapie','prozedere'))
    fields=[f for f in FIELDS if yes('Feld '+DOCUMENT_LABELS[f]+' verwenden?',f in old_fields)]
    if not fields: raise ValueError('Mindestens ein Feld auswählen.')
    print('\nSpeichernutzung der Sprechertrennung:')
    for key,label in DIARIZATION_MODES.items(): print(key+' — '+label)
    print('Zusammen mit Whisper folgt dessen Ladezustand; seriell gibt den GPU-Speicher zwischen den Schritten frei.')
    print('Immer geladen benötigt zusätzlich zum LLM GPU-Speicher. Bei knappem VRAM seriell wählen.')
    while True:
        old_diar=previous.get('DiarizationMode') or ('resident' if previous.get('ParallelModel') else 'serial')
        diarization_mode=ask('Sprechertrennung: resident / with_asr / serial',old_diar if old_diar in DIARIZATION_MODES else 'serial')
        if diarization_mode in DIARIZATION_MODES: break
        print('Bitte resident, with_asr oder serial wählen.')
    prompt=prompt_edit(previous.get('PromptText') or (ROOT/'prompt_documentation.txt').read_text())
    remote=ask('Anderer Commander für LLM (optional; - = entfernen)',previous.get('RemoteLlmUrl',''))
    if remote=='-':remote=''
    if remote:
        from urllib.parse import urlsplit
        u=urlsplit(remote)
        if u.scheme not in ('http','https') or not u.hostname or not u.port or u.username or u.path not in ('','/') or u.query or u.fragment: raise ValueError('Ungültige LLM-Commander-Adresse.')
    auth=yes('Commander-Zugang mit Token schützen?',previous.get('AuthEnabled',False))
    old_tokens=previous_server_tokens() if auth or remote else {}
    token=token_answer('Commander-Token',old_tokens.get('KIENZLEDOKU_COMMANDER_TOKEN','')) if auth else ''
    old_remote=old_tokens.get('KIENZLEDOKU_REMOTE_LLM_TOKEN','') if remote==previous.get('RemoteLlmUrl') else ''
    remote_token=token_answer('LLM-Commander-Token',old_remote,optional=True) if remote else ''
    for secret in (token,remote_token):
        if len(secret)>4096 or any(c.isspace() for c in secret): raise ValueError('Token darf keine Leerzeichen enthalten.')
    hf=os.environ.get('HF_TOKEN','')
    if not hf:
        for p in (client_config.config_dir()/'huggingface.token',Path.home()/'.cache/huggingface/token'):
            if p.is_file(): hf=p.read_text().strip();break
    if hf:
        print('Vorhandener Hugging-Face-Token erkannt (Wert bleibt verborgen).')
        if yes('Vorhandenen Hugging-Face-Token verwenden?',True): pass
        else: hf=getpass.getpass('Hugging-Face-Read-Token (unsichtbar): ')
    else: hf=getpass.getpass('Hugging-Face-Read-Token (Whisper/pyannote, unsichtbar): ')
    if not hf: raise ValueError('Hugging-Face-Token fehlt.')
    memory=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
    budget=max((n for n in (16,24,28,32) if memory/1024**3>=n+1),default=0)
    if not budget: raise ValueError('Für diesen Server mindestens 20 GiB Arbeitsspeicher einplanen.')
    if previous.get('WslRamGiB') in (16,24,28,32) and previous['WslRamGiB']<=budget:
        budget=previous['WslRamGiB']
    default_model=previous.get('DefaultModel')
    if default_model not in mapping.values():default_model=next(iter(mapping.values()))
    cfg=dict(Version=VERSION,Models=selected,DefaultModel=default_model,QualityModels=mapping,
        Profiles={k:dict(Mode='parallel' if k==parallel else 'serial') for k in selected},ParallelModel=parallel,AudioCache=previous.get('AudioCache','ram'),WslRamGiB=budget,
        GpuIndex=gpu,EnabledFields=fields,PromptText=prompt,AuthEnabled=auth,AsrOnDemand=on_demand,DiarizationMode=diarization_mode,RemoteLlmUrl=remote,
        VerifyModelFiles=previous.get('VerifyModelFiles',True),ForceModelVerification=False)
    for key in selected:
        if budget<catalog[key].get('ram_audio_min_wsl_gib',0): cfg['AudioCache']='disk'
    cfg['NativeBind']='0.0.0.0' if yes('Commander im lokalen Netzwerk anbieten?',previous.get('NativeBind')=='0.0.0.0') else '127.0.0.1'
    print('\nModellbetrieb: '+('parallel — '+catalog[parallel]['label'] if parallel else 'seriell'))
    print('Whisper: '+('erst bei Bedarf laden' if on_demand else 'beim Dienststart laden'))
    print('Sprechertrennung: '+DIARIZATION_MODES[diarization_mode])
    for grade,key in mapping.items():print(GRADE_LABELS[grade]+': '+catalog[key]['label'])
    return cfg,hf,token,remote_token

def configure_client(local,token):
    cfg=client_config.load()
    cfg['connection']['mode']=ask('FHIR-Verbindung direct oder connect',cfg['connection']['mode'])
    cfg['connection']['target']=ask('T2med-FHIR-Adresse',cfg['connection']['target'])
    cfg['connection']['ca_file']=ask('CA-Zertifikat, optional',cfg['connection']['ca_file'])
    cfg['connection']['allow_insecure_tls']=yes('Lokales T2med-Zertifikat ohne Prüfung akzeptieren?',cfg['connection']['allow_insecure_tls'])
    cfg['commander']['enabled']=True
    cfg['commander']['url']='http://127.0.0.1:8185' if local else ask('Commander-Adresse',cfg['commander']['url'])
    if not local:
        print('Ein leerer Token lässt einen vorhandenen privaten Token unverändert.')
        token=getpass.getpass('Commander-Token (optional, unsichtbar): ')
    client_config.validate(cfg)
    return cfg,token

def self_test():
    required=['kienzledoku.py','installer/linux_server.py','installer/linux_uninstall.py','linux/install_client.sh','server-windows/linux/install_server.py','server-windows/models.json','prompt_documentation.txt','native/KienzledokuWindowLinux.c','build_native_window_linux.sh']
    for name in required:
        if not (ROOT/name).is_file(): raise ValueError('Datei fehlt: '+name)
    for path in [ROOT/'installer/linux_cli.py',ROOT/'installer/linux_server.py',ROOT/'installer/linux_uninstall.py']:
        compile(path.read_bytes(),str(path),'exec')
    subprocess.run(['bash','-n',str(ROOT/'linux/install_client.sh')],check=True)
    profile=(ROOT/'linux/kienzledoku.apparmor').read_text()
    assert 'userns,' in profile and 'apparmor_restrict_unprivileged_userns=0' not in profile
    print('SELF-TEST OK — kienzledoku 1.8 Linux, ohne Systemänderungen')

def uninstall(choice,remove_models,remove_settings):
    options=Uninstaller.options(choice,remove_models,remove_settings)
    client=choice in ('client','both');server=choice in ('server','both')
    helper=[sys.executable,str(ROOT/'installer/linux_uninstall.py'),'--components','server']
    if remove_models: helper.append('--remove-models')
    if remove_settings: helper.append('--remove-settings')
    local=Uninstaller()
    if client: local.plan(Uninstaller.options('client',False,remove_settings))
    if server and os.geteuid()!=0:
        if client: subprocess.run(['sudo',*helper,'--preflight'],check=True)
    if client: local.execute(Uninstaller.options('client',False,remove_settings))
    if server:
        if os.geteuid()==0: local.execute(Uninstaller.options('server',remove_models,remove_settings))
        else: subprocess.run(['sudo',*helper],check=True)
    print('\nKienzledoku 1.8 deinstalliert. Modelle: '+
          ('entfernt' if remove_models else 'beibehalten')+'; Einstellungen: '+
          ('entfernt.' if remove_settings else 'beibehalten.'))

def previous_components():
    state = client_config.config_dir()/'installer.json'
    if state.is_file():
        try:
            choice = json.loads(state.read_text()).get('components')
            if isinstance(choice,list):
                choice='both' if set(choice)=={'client','server'} else choice[0] if len(choice)==1 else None
            if choice in ('client','server','both'): return 'server' if os.geteuid()==0 else choice
            raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Gespeicherte Komponentenauswahl ist ungültig; Einstellungen werden nicht ersetzt.') from None
    server = SERVER_STATE.is_file()
    client = (client_config.config_dir()/'config.toml').is_file() and os.geteuid()!=0
    return 'both' if server and client else 'server' if server or os.geteuid()==0 else 'client'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test',action='store_true');parser.add_argument('--plan',action='store_true')
    parser.add_argument('--components',choices=('client','server','both'));parser.add_argument('--skip-packages',action='store_true')
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args()
    if args.self_test: self_test();return
    if not args.plan:
        release=Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else ''
        if 'ID=ubuntu' not in release or 'VERSION_ID="24.04"' not in release or platform.machine()!='x86_64': raise ValueError('Ubuntu 24.04 x86_64 erforderlich.')
    action='deinstallieren' if args.uninstall else ('installieren' if args.components or args.plan else ask('Aktion: installieren / deinstallieren','installieren').lower())
    if action not in ('installieren','deinstallieren'): raise ValueError('Ungültige Aktion.')
    choice=args.components or ask('Komponenten: client / server / both',previous_components())
    if choice not in ('client','server','both'): raise ValueError('Ungültige Komponentenauswahl.')
    if args.plan:
        print(json.dumps(dict(version=VERSION,action=action,components=choice,server='Commander / NVIDIA / seriell auf Abruf',client='Record + Connect / GTK4',changes=False),ensure_ascii=False,indent=2));return
    if os.geteuid()==0 and choice in ('client','both'):
        raise ValueError('Den Desktop-Client als angemeldeter Desktop-Benutzer ausführen; root ist nur für den Server vorgesehen.')
    server=choice in ('server','both');client=choice in ('client','both')
    if action=='deinstallieren':
        remove_models=yes('Heruntergeladene Kienzledoku-Modelle ebenfalls entfernen?',False) if server else False
        remove_settings=yes('Technische Einstellungen und Protokolle ebenfalls entfernen?',False)
        print('\nZusammenfassung: '+choice+' deinstallieren; Modelle: '+('entfernen' if remove_models else 'behalten')+
              '; Einstellungen: '+('entfernen' if remove_settings else 'behalten')+'.')
        if not yes('Auswahl jetzt deinstallieren?',False): return
        uninstall(choice,remove_models,remove_settings);return
    cfg=hf=token=remote_token=None
    if server: cfg,hf,token,remote_token=server_answers()
    if client: client_cfg,client_token=configure_client(server,token or '')
    if not yes('Auswahl jetzt installieren?',True): return
    if server:
        with tempfile.TemporaryDirectory(prefix='kienzledoku-install-') as temp:
            td=Path(temp);private_write(td/'config.json',json.dumps(cfg));private_write(td/'hf.token',hf)
            private_write(td/'commander.token',token);private_write(td/'remote.token',remote_token)
            privilege=[] if os.geteuid()==0 else ['sudo']
            subprocess.run([*privilege,sys.executable,str(ROOT/'installer/linux_server.py'),'--source',str(ROOT),'--config',str(td/'config.json'),'--hf-token-file',str(td/'hf.token'),'--token-file',str(td/'commander.token'),'--remote-token-file',str(td/'remote.token')],check=True)
            # Generated tokens are read through sudo, never passed on the command line.
            if cfg['AuthEnabled'] and not token:
                client_token=subprocess.check_output([*privilege,sys.executable,'-c',"from pathlib import Path;print(Path('/etc/kienzledoku-server/token.env').read_text().splitlines()[0].split('=',1)[1])"],text=True).strip()
        private_write(client_config.config_dir()/'huggingface.token',hf)
    if client:
        cmd=['bash',str(ROOT/'linux/install_client.sh'),'--non-interactive']
        if args.skip_packages: cmd.append('--skip-packages')
        subprocess.run(cmd,check=True)
        client_config.save(client_cfg)
        if client_token: client_config.store_commander_token(client_token)
        elif server: (client_config.config_dir()/'commander.token').unlink(missing_ok=True)
        scheme='kienzledoku' if client_cfg['connection']['mode']=='connect' else 'kienzledoku-record'
        print('\nT2med: nach dritt suchen → Drittanbieter-Zugriffe verwalten.')
        print('Per Produktcode aktivieren → Produktcode kienzledoku eingeben und bestätigen.')
        print('Dr. Thomas Kienzle - KienzleDoku erscheint mit einem grünen Statuspunkt.')
        if production_build(ROOT): print('Für die URL den aktivierten Eintrag KienzleDoku verwenden.')
        else: print('Aktueller Teststand mit Demo-Key: für die URL weiter T2med-Demo → Bearbeiten wählen.')
        print('Bezeichnung: kienzledoku record. Vollständige Adresse kopieren:\n')
        print(scheme+'://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}')
        print('\nAusführliche Anleitung: '+DOCS)
    private_write(client_config.config_dir()/'installer.json',json.dumps({'components':choice}))
    print('\nkienzledoku 1.8 installiert.')
if __name__=='__main__':
    try: main()
    except ValueError as exc:
        print('Vorgang nicht abgeschlossen: '+str(exc),file=sys.stderr);sys.exit(1)
    except subprocess.CalledProcessError:
        print('Vorgang nicht abgeschlossen: Ein Installations- oder Systemdienstschritt ist fehlgeschlagen.',file=sys.stderr);sys.exit(1)
    except OSError:
        print('Vorgang nicht abgeschlossen: Dateien, Pfade und Berechtigungen prüfen.',file=sys.stderr);sys.exit(1)
    except (KeyboardInterrupt,EOFError):
        print('\nVorgang abgebrochen.',file=sys.stderr);sys.exit(130)
