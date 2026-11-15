#!/usr/bin/env python3
"""Private local installer UI. The installer alone decides when to mutate files."""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import signal
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if sys.platform == 'win32':
    from installer.windows_core import Installer, bootstrap, plan, address, ROOT, Uninstaller
else:
    from installer.core import Installer, bootstrap, plan, address, ROOT
    from installer.uninstall_macos import Uninstaller
from kienzledoku_http import SecureLocalHandler, configure_server

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def probe(url,token=''):
    url=address(url)
    if not isinstance(token,str) or len(token)>4096 or any(c.isspace() for c in token): raise ValueError('Ungültiges Commander-Token.')
    opener=build_opener(ProxyHandler({}),NoRedirect())
    def get(path):
        request=Request(url+path,headers={'Authorization':'Bearer '+token} if token else {})
        try:
            with opener.open(request,timeout=10) as response:
                raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024: raise ValueError()
                return json.loads(raw)
        except Exception: raise ValueError('Commander ist nicht erreichbar oder hat den Zugriff abgelehnt. Adresse und optionales Token prüfen.') from None
    profiles=get('/v1/runtime/profiles'); settings=get('/v1/documentation/settings')
    if not isinstance(profiles,dict) or not isinstance(profiles.get('data'),list) or not isinstance(settings,dict): raise ValueError('Commander liefert eine ungültige Konfiguration.')
    from kienzledoku_document import validate_fields
    fields=list(validate_fields(settings.get('fields')))
    prompt=settings.get('prompt')
    if not isinstance(prompt,str): raise ValueError('Der Commander liefert keinen aktiven Prompt.')
    return dict(profiles=profiles['data'],fields=fields,prompt=prompt)


def handler(installer,csrf,uninstaller=None):
    uninstaller=uninstaller or Uninstaller(installer.support)
    operation_lock=threading.Lock()
    class Handler(SecureLocalHandler,BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send_error(self,code,message=None,explain=None): self.json({'error':'Lokaler Zugriff verweigert.'},code)
        def respond(self,raw,kind='application/json',code=200):
            self.send_response(code)
            self.send_header('Content-Type',kind+'; charset=utf-8'); self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers(); self.wfile.write(raw)
        def json(self,data,code=200): self.respond(json.dumps(data,ensure_ascii=False).encode(),code=code)
        def do_GET(self):
            if not self.authorize(): return
            path=urlsplit(self.path).path
            if path=='/': self.respond((ROOT/'installer/ui.html').read_bytes(),'text/html')
            elif path=='/api/bootstrap': self.json(dict(bootstrap(installer.hw,installer.support),csrf=csrf))
            elif path=='/api/status': self.json(installer.snapshot())
            elif path=='/api/uninstall': self.json(dict(uninstaller.inspect(),status=uninstaller.snapshot()))
            elif path=='/api/uninstall/status': self.json(uninstaller.snapshot())
            elif path in ('/assets/kienzledoku-record.svg','/logo.svg'):
                self.respond((ROOT/'assets/kienzledoku-record.svg').read_bytes(),'image/svg+xml')
            elif path in ('/assets/t2med-drittanbieter-suche.png','/assets/t2med-drittanbieter-url.png','/assets/t2med-produktcode-aktivieren.png','/assets/t2med-produktcode-kienzledoku.png','/assets/t2med-kienzledoku-aktiv.png'):
                self.respond((ROOT/'docs/images'/path.rsplit('/',1)[1]).read_bytes(),'image/png')
            else: self.json({'error':'Nicht gefunden.'},404)
        def do_POST(self):
            if not self.authorize(): return
            if not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),csrf): self.json({'error':'Ungültige Anfrage.'},403); return
            try:
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json': raise ValueError('Ungültige Anfrage.')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=128*1024: raise ValueError('Ungültige Anfragelänge.')
                body=json.loads(self.rfile.read(int(lengths[0])))
                if not isinstance(body,dict): raise ValueError('Ungültige Anfrage.')
                path=urlsplit(self.path).path
                if path=='/api/validate': self.json(plan(body,installer.hw))
                elif path=='/api/install':
                    with operation_lock:
                        if uninstaller.snapshot()['running']: raise ValueError('Die Deinstallation läuft bereits.')
                        installer.start(body)
                    self.json({'started':True})
                elif path=='/api/uninstall':
                    with operation_lock:
                        if installer.snapshot()['running']: raise ValueError('Die Installation läuft bereits.')
                        uninstaller.start(body)
                    self.json({'started':True})
                elif path=='/api/probe': self.json(probe(body.get('url',''),body.get('token','')))
                elif path=='/api/token': self.json({'token':secrets.token_urlsafe(32)})
                elif path=='/api/cancel': installer.cancel.set(); self.json({'cancelled':True})
                else: self.json({'error':'Nicht gefunden.'},404)
            except (ValueError,TypeError,KeyError) as exc:
                self.json({'error':str(exc) if isinstance(exc,ValueError) else 'Ungültige Einstellungen.'},400)
    return Handler


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--serve',action='store_true'); parser.add_argument('--stdio',action='store_true'); parser.parse_args()
    installer=Installer(); uninstaller=Uninstaller(installer.support)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(installer,secrets.token_urlsafe(32),uninstaller))
    server.daemon_threads=True
    def stop(*_):
        installer.cancel.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    print(configure_server(server),flush=True)
    try: server.serve_forever(poll_interval=.2)
    finally:
        installer.cancel.set(); server.server_close()
        # Give owned subprocess cleanup a bounded opportunity before exiting.
        import time
        deadline=time.monotonic()+12
        while (installer.snapshot()['running'] or uninstaller.snapshot()['running']) and time.monotonic()<deadline: time.sleep(.1)
    return 0

if __name__=='__main__': raise SystemExit(main())
