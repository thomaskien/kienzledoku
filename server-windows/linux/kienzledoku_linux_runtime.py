"""Supported Ubuntu releases and an isolated, checksum-pinned Python 3.12.

Ubuntu's system Python is never replaced. 24.04 keeps its distribution Python;
26.04 uses the same Python ABI as the reviewed client and server dependencies.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
PYTHON_SHA256 = 'ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20'
PYTHON_BYTES = 34505639
IDENTITY = {'python': '3.12.16', 'sha256': PYTHON_SHA256}


def ubuntu_version(release=None, machine=None):
    if release is None:
        release = Path('/etc/os-release').read_text()
    values = {}
    for line in release.splitlines():
        key, separator, value = line.partition('=')
        if separator and key in ('ID', 'VERSION_ID'):
            tokens = shlex.split(value, comments=True)
            if len(tokens) != 1 or key in values:
                raise ValueError('Ungültige Ubuntu-Versionsangabe.')
            values[key] = tokens[0]
    if values.get('ID') != 'ubuntu' or values.get('VERSION_ID') not in ('24.04', '26.04') or (machine or platform.machine()) != 'x86_64':
        raise ValueError('Ubuntu 24.04 oder 26.04 LTS x86_64 erforderlich.')
    return values['VERSION_ID']


def python_info(python):
    try:
        raw = subprocess.check_output([str(python), '-I', '-c',
            'import json,sys,ssl,ctypes,sqlite3; print(json.dumps([list(sys.version_info[:3]),sys.base_prefix]))'],
            text=True, stderr=subprocess.DEVNULL, timeout=30)
        return json.loads(raw)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def checked_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part in (Path('/tmp'), Path('/var')):
            continue
        if part.is_symlink():
            raise ValueError('Verknüpfter Python-Installationspfad; nichts geändert.')
    return path


def download(target):
    print('Python 3.12 für Ubuntu 26.04 wird bereitgestellt (33 MiB).', file=sys.stderr, flush=True)
    request = urllib.request.Request(PYTHON_URL, headers={'User-Agent': 'kienzledoku-installer/1.8.3'})
    digest = hashlib.sha256()
    count, last = 0, -1
    with urllib.request.urlopen(request, timeout=60) as source, target.open('xb') as output:
        while block := source.read(1024 * 1024):
            count += len(block)
            if count > PYTHON_BYTES:
                raise ValueError('Python-Download ist größer als erwartet.')
            output.write(block)
            digest.update(block)
            progress = count * 100 // PYTHON_BYTES
            if progress // 10 != last:
                print(f'Python: {progress} %', file=sys.stderr, flush=True)
                last = progress // 10
    if count != PYTHON_BYTES or digest.hexdigest() != PYTHON_SHA256:
        raise ValueError('Python-Download unvollständig oder SHA-256-Prüfung fehlgeschlagen.')


def ensure_python(target, release=None):
    release = release or ubuntu_version()
    if release == '24.04':
        python = Path('/usr/bin/python3.12')
        info = python_info(python)
        if not info or info[0][:2] != [3, 12]:
            raise ValueError('Ubuntu-Python 3.12 fehlt. Bitte python3.12 und python3.12-venv installieren.')
        return python
    if release != '26.04':
        raise ValueError('Nicht unterstützte Ubuntu-Version.')
    target = checked_path(target)
    python = target/'bin/python3.12'
    marker = target/'.kienzledoku-python.json'
    if target.exists():
        if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()) != IDENTITY:
            raise ValueError('Unbekannte Python-Laufzeit am Installationsziel; nichts ersetzt.')
        info = python_info(python)
        if info and info[0] == [3, 12, 16]:
            return python
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.kienzledoku-python-', dir=target.parent) as folder:
        work = Path(folder)
        archive = work/'python.tar.gz'
        download(archive)
        with tarfile.open(archive) as handle:
            # Python's data filter rejects escaping paths/links and special files.
            handle.extractall(work/'unpacked', filter='data')
        candidate = work/'unpacked/python'
        info = python_info(candidate/'bin/python3.12')
        if not info or info[0] != [3, 12, 16]:
            raise ValueError('Die geprüfte Python-Laufzeit konnte nicht gestartet werden.')
        (candidate/marker.name).write_text(json.dumps(IDENTITY)+'\n')
        if target.exists():
            target.rename(work/'previous')
        try:
            candidate.rename(target)
        except Exception:
            if (work/'previous').exists():
                (work/'previous').rename(target)
            raise
    return python


def ensure_venv(python, target):
    """Recreate only an owned venv with a broken/wrong base after an OS upgrade."""
    target = checked_path(target)
    expected = python_info(python)
    if not expected or expected[0][:2] != [3, 12]:
        raise ValueError('Python 3.12 für die Paketinstallation erforderlich.')
    actual = python_info(target/'bin/python')
    if actual and actual[0][:2] == [3, 12] and actual[1] == expected[1]:
        return
    if target.exists() and not (target/'pyvenv.cfg').is_file():
        raise ValueError('Unbekanntes Verzeichnis statt Python-Umgebung; nichts entfernt.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.kienzledoku-venv-', dir=target.parent) as folder:
        previous = Path(folder)/'previous'
        if target.exists():
            target.rename(previous)
        try:
            subprocess.run([str(python), '-m', 'venv', str(target)], check=True)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if previous.exists():
                previous.rename(target)
            raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    version = ubuntu_version()
    if args.check:
        print(version)
    elif args.target:
        print(ensure_python(args.target, version))
    else:
        parser.error('--check oder --target erforderlich')
