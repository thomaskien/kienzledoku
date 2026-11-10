"""systemd start barrier: require the worker control socket to answer."""
from pathlib import Path
import json
import socket
import sys
import time

deadline=time.monotonic()+570
while time.monotonic()<deadline:
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(2)
            s.connect(sys.argv[1])
            s.sendall(b'{"operation":"status"}\n')
            value=json.loads(s.makefile('rb').readline(65537))
        if value.get('ok') is True:
            sys.exit(0)
    except (OSError,ValueError):
        pass
    time.sleep(.5)
sys.exit('Worker wurde nicht bereit.')
