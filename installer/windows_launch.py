"""Own the private wizard server and native window for exactly one setup run."""
import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from installer import wizard
from installer.windows_core import Installer, Uninstaller, ROOT
from kienzledoku_http import configure_server


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--ready-file',type=Path,required=True); args=parser.parse_args()
    server=None; process=None
    try:
        installer=Installer(); uninstaller=Uninstaller(installer.support)
        server=ThreadingHTTPServer(('127.0.0.1',0),wizard.handler(installer,secrets.token_urlsafe(32),uninstaller));server.daemon_threads=True
        url=configure_server(server)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        with tempfile.TemporaryDirectory(prefix='kienzledoku-installer-webview-') as profile:
            process=subprocess.Popen([str(ROOT/'kienzledoku_window.exe'),'--installer',profile,str(ROOT/'assets/kienzledoku-record.ico')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            process.stdin.write((url+'\n').encode());process.stdin.close()
            if process.stdout.readline().strip()!=b'WINDOW_READY': raise RuntimeError('Das Installationsfenster konnte nicht gestartet werden.')
            args.ready_file.write_text('ready',encoding='utf-8')
            process.wait()
            # Native close is blocked while operations run. Also retain backend on a host crash.
            while installer.snapshot()['running'] or uninstaller.snapshot()['running']: time.sleep(.25)
        return process.returncode
    except Exception:
        args.ready_file.write_text('Der Installationsassistent konnte nicht gestartet werden. Bitte WebView2 und das Installationspaket prüfen.',encoding='utf-8')
        return 1
    finally:
        if server: server.shutdown();server.server_close()

if __name__=='__main__': raise SystemExit(main())
