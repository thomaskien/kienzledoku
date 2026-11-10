"""Own a short-lived compiled Connect proxy; no fallback and no key exchange."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import urllib.parse

class ConnectProxy:
    def __init__(self, connection, binary=None):
        self.process = None
        self.token = ''
        binary = Path(binary or Path(__file__).with_name('kienzleconnect.exe' if sys.platform == 'win32' else 'kienzleconnect'))
        if not binary.is_file():
            raise RuntimeError('Connect fehlt. Bitte Connect installieren oder vor einem neuen Vorgang ausdrücklich Direktbetrieb wählen.')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        self.process = subprocess.Popen([str(binary), 'serve-stdio'], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       text=True, encoding='utf-8', **options)
        try:
            payload = {key: connection[key] for key in ('target', 'ca_file', 'allow_insecure_tls')}
            self.process.stdin.write(json.dumps(payload) + '\n')
            self.process.stdin.flush()
            result = queue.Queue()
            def read_handshake():
                try:
                    result.put(self.process.stdout.readline(8192))
                except Exception:
                    result.put('')
            threading.Thread(target=read_handshake, daemon=True).start()
            reply = json.loads(result.get(timeout=10))
            parsed = urllib.parse.urlsplit(reply['url'])
            if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                    or parsed.path or parsed.query or parsed.fragment or parsed.username):
                raise ValueError('Ungültige Connect-Adresse')
            if not isinstance(reply['token'], str) or len(reply['token']) < 32:
                raise ValueError('Ungültige Connect-Sitzung')
            self.url, self.token = reply['url'], reply['token']
        except Exception:
            self.close()
            raise RuntimeError('Connect konnte nicht gestartet werden. Ziel und TLS-Einstellungen prüfen.') from None

    def close(self):
        self.token = ''
        if self.process is None:
            return
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except Exception:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        finally:
            if self.process.stdout:
                self.process.stdout.close()
