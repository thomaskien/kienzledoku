"""Private local-server handoff and T2med launch URL; never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import kienzledoku_config as config

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--local-commander-token-file',type=Path)
    parser.add_argument('--launch-url',action='store_true')
    parser.add_argument('--wizard-config',type=Path)
    args=parser.parse_args()
    cfg=config.load()
    if args.wizard_config:
        selected=json.loads(args.wizard_config.read_text(encoding='utf-8-sig'))
        cfg['connection'].update(mode=selected['connection_mode'],target=selected['t2med_url'],allow_insecure_tls=selected['t2med_insecure'])
        cfg['commander'].update(enabled=True,url=selected['commander_url'],token_file='')
        token=selected['commander_token']
        if selected['mode']=='combined':
            cfg['commander']['url']='http://127.0.0.1:8185'
            token=(Path(os.environ['LOCALAPPDATA'])/'kienzledoku-server/client.token').read_text(encoding='utf-8-sig').strip() if selected['auth_enabled'] else ''
        config.validate(cfg)
        # Applied under the installer's update lock. Restore private files if saving fails.
        directory=config.config_dir();directory.mkdir(parents=True,exist_ok=True)
        files=[config.config_path(),directory/'commander-token.dpapi',directory/'commander.token']
        before={p:p.read_bytes() if p.exists() else None for p in files}
        try:
            if token: config.store_commander_token(token)
            else:
                for p in files[1:]: p.unlink(missing_ok=True)
            config.save(cfg)
        except Exception:
            for p,data in before.items():
                if data is None: p.unlink(missing_ok=True)
                else: p.write_bytes(data);p.chmod(0o600)
            raise
    if args.local_commander_token_file is not None:
        token=args.local_commander_token_file.read_text(encoding='utf-8-sig').strip()
        cfg['commander'].update(enabled=True,url='http://127.0.0.1:8185',token_file='')
        config.save(cfg)
        if token: config.store_commander_token(token)
        else:
            for name in ('commander-token.dpapi','commander.token'):
                (config.config_dir()/name).unlink(missing_ok=True)
    if args.launch_url:
        scheme='kienzledoku' if cfg['connection']['mode']=='connect' else 'kienzledoku-record'
        print(scheme+'://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}')
if __name__=='__main__': main()
