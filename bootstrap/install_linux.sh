#!/usr/bin/env bash
# Standalone download starter. The versioned installer remains inside its release archive.
set -euo pipefail
command -v python3 >/dev/null 2>&1 || { printf '%s\n' 'Python 3 fehlt. Bitte python3 installieren.' >&2; exit 1; }
# Keep the original terminal on fd 3 while Python reads its source from stdin.
python3 - "$@" 3<&0 <<'PYTHON'
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'thomaskien/kienzledoku'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases'
PATTERN = re.compile(r'kienzledoku-(\d+(?:\.\d+){1,3})-linux-x86_64\.tar\.gz')
MAX_ARCHIVE = 2 * 1024**3
MAX_UNPACKED = 4 * 1024**3


class InstallError(Exception):
    pass


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'KienzleDoku-Linux-Installer',
        'Accept': 'application/vnd.github+json' if url.startswith(API) else 'application/octet-stream',
    }), timeout=60)


def releases():
    result = []
    for page in range(1, 11):
        with request(API + '?per_page=100&page=' + str(page)) as response:
            data = response.read(8 * 1024**2 + 1)
        if len(data) > 8 * 1024**2:
            raise InstallError('GitHub-Antwort ist unerwartet groß.')
        batch = json.loads(data)
        if not isinstance(batch, list):
            raise InstallError('GitHub lieferte keine Release-Liste.')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise InstallError('Release-Liste unvollständig. Bitte die GitHub-Downloads manuell prüfen.')


def select_release(items):
    candidates = []
    for release in items:
        if release.get('draft') or release.get('prerelease'):
            continue
        for asset in release.get('assets', []):
            match = PATTERN.fullmatch(asset.get('name', ''))
            if match and asset.get('state') == 'uploaded':
                version = tuple(map(int, match.group(1).split('.')))
                candidates.append((version + (0,) * (4-len(version)), release, asset))
    if not candidates:
        raise InstallError('Noch kein freigegebenes Linux-Installationspaket auf GitHub vorhanden. '
                           'Die gemeinsamen Installer folgen nach Freigabe. Es wurde nichts installiert.')
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise InstallError('Die neueste Linux-Version ist mehrfach vorhanden; bitte die Releases prüfen.')
    _, release, archive = candidates[0]
    checksums = [a for a in release['assets'] if a.get('name') == archive['name'] + '.sha256'
                 and a.get('state') == 'uploaded']
    if len(checksums) != 1:
        raise InstallError('Zur neuesten Linux-Version fehlt eine eindeutige SHA-256-Datei. Abbruch.')
    for asset in (archive, checksums[0]):
        expected = ('https://github.com/' + REPOSITORY + '/releases/download/'
                    + urllib.parse.quote(release['tag_name'], safe='') + '/'
                    + urllib.parse.quote(asset['name'], safe=''))
        if asset.get('browser_download_url') != expected:
            raise InstallError('Unerwartetes Downloadziel. Abbruch vor dem Download.')
        if not isinstance(asset.get('size'), int) or asset['size'] <= 0:
            raise InstallError('Ungültige Größenangabe für das Release-Paket.')
    return archive, checksums[0]


def download(asset, destination, limit):
    if asset['size'] > limit:
        raise InstallError('Download überschreitet die erwartete Größe: ' + asset['name'])
    count = 0
    progress = -1
    print('Lade ' + asset['name'], flush=True)
    with request(asset['browser_download_url']) as response, destination.open('xb') as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > asset['size'] or count > limit:
                raise InstallError('Download ist größer als angekündigt.')
            target.write(chunk)
            percent = count * 100 // asset['size']
            if percent // 10 != progress:
                print(f'  {percent}% ({count / 1024**2:.1f} / {asset["size"] / 1024**2:.1f} MiB)', flush=True)
                progress = percent // 10
    if count != asset['size']:
        raise InstallError('Download ist unvollständig: ' + asset['name'])


def verify_checksum(archive, checksum):
    text = checksum.read_text(encoding='ascii').strip()
    match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?([^\r\n]+)', text)
    if not match or match.group(2) != archive.name:
        raise InstallError('Prüfsummendatei passt nicht zum Linux-Archiv.')
    digest = hashlib.sha256()
    with archive.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != match.group(1).lower():
        raise InstallError('SHA-256-Prüfung fehlgeschlagen. Es wird nichts ausgeführt.')
    print('SHA-256-Prüfung erfolgreich.', flush=True)


def extract_archive(archive, destination):
    root_name = archive.name[:-7]  # remove .tar.gz
    with tarfile.open(archive, 'r:gz') as handle:
        members = []
        names = set()
        total = 0
        for member in handle:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] != root_name or not (member.isdir() or member.isfile())
                    or str(path) in names or '\\' in member.name):
                raise InstallError('Unsicherer oder unerwarteter Archivinhalt. Abbruch.')
            if len(path.parts) == 1 and not member.isdir():
                raise InstallError('Ungültiger Paketordner.')
            total += member.size
            if len(members) >= 100000 or total > MAX_UNPACKED:
                raise InstallError('Entpacktes Paket überschreitet die Größenbegrenzung.')
            names.add(str(path))
            members.append(member)
        # Only regular files/directories, no links or archive-controlled owners/modes.
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    package = destination / root_name
    if not (package/'install_linux.sh').is_file() or not (package/'installer/linux_cli.py').is_file():
        raise InstallError('Archiv enthält nicht den gemeinsamen Linux-Installer.')
    return package


def main(args):
    if '--help' in args or '-h' in args:
        print('KienzleDoku Linux-Download-Starter\n'
              '  bash install_linux.sh [--components client|server|both] [Installer-Optionen]\n'
              'Lädt die neueste stabile Linux-Ausgabe, prüft SHA-256 und startet den Installer.\n'
              'Client/beides als Desktop-Benutzer; als root nur --components server.\n'
              'Ohne passendes freigegebenes Release erfolgt keine Installation.')
        return 0
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise InstallError('Dieser Starter ist für Linux x86_64 (Ubuntu 24.04) vorgesehen.')
    components = None
    for index, arg in enumerate(args):
        if arg == '--components' and index + 1 < len(args):
            components = args[index + 1]
        elif arg.startswith('--components='):
            components = arg.split('=', 1)[1]
    if os.geteuid() == 0 and components != 'server':
        raise InstallError('Als root bitte ausdrücklich --components server wählen. '
                           'Client/beides als angemeldeter Desktop-Benutzer installieren.')
    archive, checksum = select_release(releases())
    print('Ausgewählt: ' + archive['name'], flush=True)
    with tempfile.TemporaryDirectory(prefix='kienzledoku-download-') as temporary:
        folder = Path(temporary)
        archive_path, checksum_path = folder/archive['name'], folder/checksum['name']
        download(checksum, checksum_path, 4096)
        download(archive, archive_path, MAX_ARCHIVE)
        verify_checksum(archive_path, checksum_path)
        package = extract_archive(archive_path, folder)
        print('Starte den geprüften Installer.', flush=True)
        # fd 3 preserves interactive input; no pipe-to-shell installer execution.
        return subprocess.run(['bash', str(package/'install_linux.sh'), *args],
                              cwd=package, stdin=3).returncode


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (InstallError, OSError, ValueError, KeyError, tarfile.TarError, urllib.error.URLError) as exc:
        print('KienzleDoku: ' + str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nKienzleDoku: abgebrochen.', file=sys.stderr)
        sys.exit(130)
PYTHON
