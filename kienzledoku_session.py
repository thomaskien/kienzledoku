"""Per-login session exclusion and crash recovery. No OAuth/API credentials persisted."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
from kienzledoku_config import config_dir

_HANDLE = None


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


def _focus_existing(link):
    if sys.platform != 'win32' or link is None:
        return False
    try:
        info = json.loads((session_dir() / 'active.json').read_text(encoding='utf-8'))
        if info['context_hash'] != context_hash(link):
            return False
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
            if pid.value == info['window_pid'] and user32.IsWindowVisible(hwnd):
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
    if process is not None:
        path = session_dir() / 'active.json'
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'context_hash': context_hash(link), 'window_pid': process.pid}, handle)
        os.chmod(path, 0o600)


def unregister_window():
    try:
        (session_dir() / 'active.json').unlink()
    except FileNotFoundError:
        pass


def acquire(link=None):
    global _HANDLE
    if _HANDLE:
        return True
    handle = open(session_dir() / 'record.lock', 'a+b')
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
        if _focus_existing(link):
            return False
        raise RuntimeError('In dieser Anmeldesitzung ist kienzledoku record bereits geöffnet. Bitte das vorhandene Fenster abschließen oder bewusst schließen, bevor ein anderer Patient geöffnet wird.') from None
    _HANDLE = handle
    return True


def context_hash(link):
    return hashlib.sha256((link['fhir_base_url'] + '\n' + link['context_id']).encode('utf-8')).hexdigest()


class Recovery:
    def __init__(self, link):
        self.path = session_dir() / 'recovery.json'
        self.identity = context_hash(link)
        self.lock = threading.Lock()
        self.previous = None
        if self.path.exists():
            try:
                self.previous = json.loads(self.path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                raise RuntimeError('Eine Wiederherstellungsdatei ist beschädigt. Vor einem neuen Vorgang bitte die Datei im Sitzungsverzeichnis sichern und prüfen.') from None

    def save(self, state):
        speech = state.speech.snapshot() if state.speech else {}
        payload = {'context_hash': self.identity, 'documentation': state.documentation,
                   'transcript': speech.get('diarized_text') or speech.get('live_transcript', ''),
                   'audio_base_transcript': speech.get('audio_base_transcript', ''),
                   'audio_base_diarized': speech.get('audio_base_diarized', ''),
                   'output_mode': state.output_mode, 'single_code': state.single_code,
                   'write_uncertain': state.write_uncertain, 'audio': speech.get('interrupted_audio', '')}
        with self.lock:
            fd, temp = tempfile.mkstemp(prefix='.recovery-', dir=str(self.path.parent))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    json.dump(payload, fh, ensure_ascii=False)
                    fh.flush(); os.fsync(fh.fileno())
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)

    def clear(self):
        with self.lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.previous = None
            # Only application-owned spool directories in this locked login session.
            for directory in self.path.parent.glob('audio-*'):
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory, ignore_errors=True)
