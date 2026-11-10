"""Loopback UI authentication shared by Record and its independent settings UI."""
from http.cookies import SimpleCookie
import secrets
import urllib.parse

class SecureLocalHandler:
    def authorize(self):
        host = '127.0.0.1:%d' % self.server.server_address[1]
        if self.headers.get('Host') != host or self.headers.get('Origin', 'http://' + host) != 'http://' + host:
            self.send_error(403, 'Lokaler Zugriff verweigert')
            return False
        parsed = urllib.parse.urlsplit(self.path)
        cookie_name = 'record_' + str(self.server.server_address[1])
        if self.command == 'GET' and parsed.path == '/open':
            token = urllib.parse.parse_qs(parsed.query).get('token', [''])[0]
            if secrets.compare_digest(token, self.server.ui_token):
                # Commit a local document before navigating to the application.
                # A server redirect can retain the external navigation context
                # and withhold a newly set SameSite=Strict cookie in Chromium.
                nonce = secrets.token_urlsafe(24)
                data = ('<!doctype html><html lang="de"><meta charset="utf-8">'
                        '<title>kienzledoku record</title>'
                        '<p>kienzledoku record wird geöffnet. <a href="/">Weiter</a></p>'
                        '<script nonce="%s">window.location.replace("/");</script></html>'
                        % nonce).encode('utf-8')
                self.send_response(200)
                self.send_header('Set-Cookie', '%s=%s; HttpOnly; SameSite=Strict; Path=/' % (cookie_name, token))
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-%s'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'" % nonce)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return False
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie[cookie_name].value if cookie_name in cookie else ''
        except Exception:
            token = ''
        if not secrets.compare_digest(token, self.server.ui_token):
            self.send_error(403, 'Sitzung nicht berechtigt')
            return False
        return True

    def read_form(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Unzulässige Übertragung')
        raw_length = self.headers.get('Content-Length', '')
        if not raw_length.isdigit() or not 0 <= int(raw_length) <= 1024 * 1024:
            raise ValueError('Ungültige Anfragelänge')
        data = self.rfile.read(int(raw_length)).decode('utf-8')
        return urllib.parse.parse_qs(data, keep_blank_values=True)


def configure_server(server):
    server.ui_token = secrets.token_urlsafe(32)
    return 'http://127.0.0.1:%d/open?token=%s' % (server.server_address[1], server.ui_token)
