"""Local synthetic HTTPS endpoint; never uses T2med or a real credential.

localhost-key.pem is a public test fixture with no access to any real service.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import threading
import unittest

from kienzledoku_connect import ConnectProxy
from kienzledoku_config import defaults

ROOT = Path(__file__).resolve().parent.parent
BINARY = Path(os.environ.get('KIENZLEDOKU_TEST_CONNECT', str(ROOT / ('kienzleconnect.exe' if os.name == 'nt' else 'kienzleconnect'))))

@unittest.skipUnless(BINARY.is_file(), 'Build Connect first to run the real-process transport test')
class ConnectTransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, self.headers, body))
                self.send_response(422)
                self.send_header('Content-Type', 'application/fhir+json')
                self.send_header('ETag', 'W/"test"')
                self.end_headers()
                self.wfile.write(b'{"resourceType":"OperationOutcome"}')
        self.target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        fixture = ROOT / 'tests/fixtures'
        ctx.load_cert_chain(str(fixture / 'localhost-cert.pem'), str(fixture / 'localhost-key.pem'))
        self.target.socket = ctx.wrap_socket(self.target.socket, server_side=True)
        self.thread = threading.Thread(target=self.target.serve_forever, daemon=True)
        self.thread.start()
        cfg = defaults()['connection']
        cfg.update(target='https://127.0.0.1:%d/aps/fhir/api/r4' % self.target.server_address[1],
                   ca_file=str(fixture / 'localhost-cert.pem'))
        self.proxy = ConnectProxy(cfg, binary=BINARY)
    def tearDown(self):
        self.proxy.close()
        self.assertIsNotNone(self.proxy.process.poll())
        self.target.shutdown(); self.target.server_close(); self.thread.join()
    def test_real_process_preserves_payload_oauth_status_and_replaces_every_old_key(self):
        from urllib.parse import urlsplit
        port = urlsplit(self.proxy.url).port
        client = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        body = b'{ "resourceType": "Bundle", "entry": [] }'
        client.putrequest('POST', '/?context=a%2Bb&context=two')
        for key, value in [('X-API-Key','obsolete-one'), ('x-api-key','obsolete-two'),
                           ('Authorization','Bearer synthetic-oauth'),
                           ('Content-Type','application/fhir+json'),
                           ('Content-Length',str(len(body))),
                           ('X-Kienzledoku-Connect-Token',self.proxy.token)]:
            client.putheader(key, value)
        client.endheaders(body)
        response = client.getresponse()
        self.assertEqual(response.status, 422)
        self.assertEqual(response.getheader('ETag'), 'W/"test"')
        self.assertEqual(response.read(), b'{"resourceType":"OperationOutcome"}')
        client.close()
        self.assertEqual(len(self.requests),1)
        path, headers, received = self.requests[0]
        self.assertEqual(path,'/aps/fhir/api/r4?context=a%2Bb&context=two')
        self.assertEqual(received,body)
        self.assertEqual(headers['Authorization'],'Bearer synthetic-oauth')
        self.assertEqual(len(headers.get_all('X-API-Key')),1)
        self.assertNotIn(headers['X-API-Key'],('obsolete-one','obsolete-two'))
        self.assertIsNone(headers.get('X-Kienzledoku-Connect-Token'))
