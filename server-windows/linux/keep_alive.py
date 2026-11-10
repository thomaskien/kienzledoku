#!/usr/bin/env python3
"""An attached wsl.exe session keeps this distro alive while its server runs.

systemd services alone are not a WSL lifetime reference. Stop terminates the
own distro after the server has shut down; other distributions are untouched.
"""
import fcntl
import os
from pathlib import Path
import subprocess
import time

def main():
    if os.environ.get('WSL_DISTRO_NAME')!='kienzledoku-server':
        raise SystemExit('Falsche WSL-Instanz.')
    with Path('/run/kienzledoku-server-keepalive.lock').open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        while True:
            status=subprocess.run(['systemctl','is-active','kienzledoku-commander.service'],
                                  text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL).stdout.strip()
            if status not in ('active','activating','reloading'): return
            time.sleep(2)

if __name__=='__main__':main()
