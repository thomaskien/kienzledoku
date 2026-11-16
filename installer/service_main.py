"""Launch Commander with private optional credentials, never in argv/plists."""
import json
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))

def main():
    check='--check-config' in sys.argv
    args=[arg for arg in sys.argv[1:] if arg!='--check-config']
    if len(args)!=2: return 2
    config,credentials=map(Path,args)
    if credentials.exists():
        info=credentials.stat()
        if info.st_mode & 0o077 or info.st_uid!=os.getuid():
            raise ValueError('Commander-Zugangsspeicher muss dem Benutzer gehören und privat sein.')
        for key,value in json.loads(credentials.read_text()).items():
            if key not in ('KIENZLEDOKU_COMMANDER_TOKEN','KIENZLEDOKU_REMOTE_LLM_TOKEN','KIENZLEDOKU_REMOTE_DIAR_TOKEN') or not isinstance(value,str) or any(c.isspace() for c in value):
                raise ValueError('Ungültiger Commander-Zugangsspeicher.')
            # Explicit installer environment takes priority during candidate checks.
            if check: os.environ.setdefault(key,value)
            else: os.environ[key]=value
    from kienzledoku_commander.__main__ import main as commander_main
    sys.argv=['kienzledoku_commander','--config',str(config)]+(['--check-config'] if check else [])
    return commander_main()

if __name__=='__main__':
    raise SystemExit(main())
