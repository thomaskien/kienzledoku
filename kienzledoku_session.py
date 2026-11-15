"""Per-login exclusion and migration of legacy patient-data artifacts."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from kienzledoku_config import config_dir

_HANDLE = None
_UPDATE_LEASE = None
_BROKER = None


class ActiveSessionError(RuntimeError):
    def __init__(self, endpoint=None, token=None):
        super(ActiveSessionError, self).__init__(
            'In dieser Anmeldesitzung ist bereits ein Patientenfenster geöffnet.')
        self.endpoint = endpoint
        self.token = token

    def request(self, show=False):
        if not self.endpoint or not self.token:
            raise RuntimeError('Das offene Fenster antwortet noch nicht.')
        req = urllib.request.Request(
            self.endpoint + ('/show' if show else '/current'),
            data=b'{}' if show else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
            method='POST' if show else 'GET')
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
            return json.loads(response.read(65537).decode('utf-8'))


def _active_info():
    try:
        path = session_dir() / 'active.json'
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or callable(getattr(os, 'getuid', None)) and info.st_uid != os.getuid()):
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value.get('port'), int) or not 1 <= value['port'] <= 65535
                or not isinstance(value.get('token'), str) or len(value['token']) < 32):
            return None
        return value
    except (OSError, ValueError, KeyError):
        return None


def session_dir():
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        ident = wintypes.DWORD()
        if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(ident)):
            raise OSError('Windows-Anmeldesitzung nicht ermittelbar')
        key = 'windows-' + str(ident.value)
    else:
        key = os.environ.get('XDG_SESSION_ID') or os.environ.get('DISPLAY') or 'desktop'
    key = re.sub(r'[^a-zA-Z0-9_-]', '_', key)
    path = config_dir() / 'sessions' / key
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _focus_process(process):
    if process is None:
        return False
    if sys.platform == 'darwin':
        try:
            script = ('tell application "System Events" to set frontmost of '
                      'first process whose unix id is %d to true' % process.pid)
            return subprocess.run(['/usr/bin/osascript', '-e', script],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=3, check=False).returncode == 0
        except Exception:
            return False
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        @callback_type
        def visit(hwnd, unused):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process.pid and user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE, including a minimized window
                user32.SetForegroundWindow(hwnd)
                user32.FlashWindow(hwnd, True)
                found.append(hwnd)
                return False
            return True
        user32.EnumWindows(visit, 0)
        return bool(found)
    except (ValueError, KeyError, OSError):
        return False


def register_window(link, process):
    if _BROKER is not None:
        _BROKER.process = process


def unregister_window():
    global _BROKER, _HANDLE, _UPDATE_LEASE
    if _BROKER is not None:
        _BROKER.close()
        _BROKER = None
    try:
        (session_dir() / 'active.json').unlink()
    except FileNotFoundError:
        pass
    if _HANDLE is not None:
        try:
            _HANDLE.close()
        finally:
            _HANDLE = None

    if _UPDATE_LEASE is not None:
        _UPDATE_LEASE.close(); _UPDATE_LEASE = None


def acquire(link=None):
    global _HANDLE, _UPDATE_LEASE
    if _HANDLE:
        return True
    from kienzledoku_update import Lease
    lease = Lease(config_dir()/'update.lock')
    try: handle = open(session_dir() / 'record.lock', 'a+b')
    except Exception:
        lease.close(); raise
    try:
        if sys.platform == 'win32':
            import msvcrt
            if handle.seek(0, 2) == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        lease.close()
        info = _active_info() or {}
        raise ActiveSessionError(
            'http://127.0.0.1:%s' % info['port'] if info.get('port') else None,
            info.get('token')) from None
    _HANDLE = handle
    _UPDATE_LEASE = lease
    return True


class ActiveSessionBroker(object):
    def __init__(self, provider):
        self.provider = provider
        self.process = None
        self.token = secrets.token_urlsafe(32)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): return
            def authorized(self):
                return secrets.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + owner.token)
            def send_value(self, value, status=200):
                data = json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store')
                self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                if not self.authorized() or self.path != '/current':
                    self.send_value({'error': 'forbidden'}, 403); return
                self.send_value(owner.provider())
            def do_POST(self):
                if not self.authorized() or self.path != '/show':
                    self.send_value({'error': 'forbidden'}, 403); return
                process = owner.process
                self.send_value({'ok': _focus_process(process)})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name='Kienzledoku-Active-IPC', daemon=True)
        self.thread.start()
        path = session_dir() / 'active.json'
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump({'port': self.server.server_address[1], 'token': self.token}, handle)
        os.chmod(str(path), 0o600)

    def close(self):
        self.server.shutdown(); self.server.server_close()
        try: (session_dir() / 'active.json').unlink()
        except FileNotFoundError: pass


def start_active_broker(provider):
    global _BROKER
    if _BROKER is not None:
        return _BROKER
    _BROKER = ActiveSessionBroker(provider)
    return _BROKER


def cleanup_legacy_patient_data(root=None):
    """Remove only known Record recovery/audio artifacts, without following links."""
    directory = Path(root) if root is not None else session_dir()
    removed = []
    for name in ('recovery.json',):
        path = directory / name
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            pass
    try:
        candidates = list(directory.iterdir())
    except FileNotFoundError:
        return removed
    for path in candidates:
        if not path.name.startswith('audio-'):
            continue
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            path.unlink()
            removed.append(path)
        elif stat.S_ISDIR(info.st_mode):
            shutil.rmtree(str(path))
            removed.append(path)
    return removed
