"""Reclaim abandoned model processes from this user's Mac installation only.

Call while holding ownership.owner(control_dir). No process is identified by
port or name alone. Record, Connect and other applications are never targets.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    uid: int
    started: str
    executable: str
    command: str


def _ps(*args):
    result = subprocess.run(['/bin/ps', *args], capture_output=True, text=True,
                            timeout=5, env=dict(os.environ, LC_ALL='C'))
    return result.stdout.strip() if result.returncode == 0 else ''


def _read_process(pid):
    row = _ps('-ww', '-p', str(pid), '-o', 'pid=,ppid=,uid=,lstart=,comm=').split(None, 8)
    if len(row) != 9:
        return None
    try:
        command = _ps('-ww', '-p', str(pid), '-o', 'command=')
        return Process(int(row[0]), int(row[1]), int(row[2]), ' '.join(row[3:8]), row[8], command)
    except ValueError:
        return None


def _role(process, support):
    if process is None or process.ppid != 1 or process.uid != os.getuid():
        return None
    try:
        parts = Path(process.executable).relative_to(support / 'versions').parts
    except ValueError:
        return None
    if not parts or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?-[0-9a-f]{8}', parts[0]):
        return None
    version = support / 'versions' / parts[0]
    for role, venv, script in (('asr', 'asr-venv', 'asr_server_mlx.py'),
                               ('diar', 'diar-venv', 'diarization_server_mps.py')):
        if parts[1:] == (venv, 'bin', 'python'):
            expected = process.executable + ' ' + str(version / 'local-ai-macos' / script)
            return role if process.command == expected else None
    if parts[1:] == ('llama', 'llama-server'):
        # The executable, local model root and Commander-only arguments must
        # all agree. Never terminate a different tool using this llama binary.
        prefix = process.executable + ' --model ' + str(support / 'models') + '/'
        if (process.command.startswith(prefix) and process.command.endswith(' --log-disable')
                and re.search(r' --alias [a-z0-9_]+ --host (127\.0\.0\.1|localhost|::1) --port \d+ --parallel ', process.command)):
            return 'llm'
    return None


def _candidates(support):
    # Enumerate executable paths first; inspect arguments only for our own
    # version directory. Nothing from ps is printed or persisted.
    for line in _ps('-ww', '-axo', 'pid=,ppid=,uid=,comm=').splitlines():
        fields = line.split(None, 3)
        if len(fields) != 4:
            continue
        try:
            pid, ppid, uid = map(int, fields[:3])
        except ValueError:
            continue
        if ppid == 1 and uid == os.getuid() and fields[3].startswith(str(support / 'versions') + '/'):
            candidate = _read_process(pid)
            if _role(candidate, support):
                yield candidate


def _terminate(candidate, support, grace=5):
    # Re-read the complete identity immediately before every signal, including
    # birth time, executable and arguments, to reject stale/reused PIDs.
    if _read_process(candidate.pid) != candidate or not _role(candidate, support):
        return False
    try:
        os.kill(candidate.pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if _read_process(candidate.pid) != candidate:
            return True
        time.sleep(.1)
    if _read_process(candidate.pid) == candidate and _role(candidate, support):
        try:
            os.kill(candidate.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if _read_process(candidate.pid) != candidate:
            return True
        time.sleep(.1)
    raise RuntimeError('Ein verwaister Kienzledoku-Modellprozess konnte nicht beendet werden.')


def cleanup_orphans(control_dir):
    """Called under the exclusive Commander lock; returns cleaned role names."""
    if sys.platform != 'darwin':
        return []  # Linux/WSL models belong to their systemd control groups.
    support = Path.home() / 'Library/Application Support/Kienzledoku'
    expected = support / 'commander/run'
    if Path(control_dir) != expected or expected.resolve() != expected:
        return []  # Custom installations need an explicit ownership policy.
    if support.stat().st_uid != os.getuid():
        return []
    cleaned = []
    for candidate in _candidates(support):
        role = _role(candidate, support)
        if _terminate(candidate, support):
            cleaned.append(role)
    return cleaned


def cleanup_after_stop(control_dir, timeout=125):
    """Wait for the previous Commander to release ownership before cleanup."""
    from .ownership import owner
    if not Path(control_dir).exists():
        return []
    deadline=time.monotonic()+timeout
    while True:
        try:
            with owner(control_dir):
                return cleanup_orphans(control_dir)
        except BlockingIOError:
            if time.monotonic()>=deadline:
                raise RuntimeError('Der bisherige Commander wurde nicht vollständig beendet. Bitte laufende Verarbeitung abschließen und erneut versuchen.') from None
            time.sleep(.2)
