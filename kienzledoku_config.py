"""Shared Record 1.3.3 configuration. Patient context and credentials never enter TOML."""
import copy
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys
import urllib.parse


def config_dir():
    override = os.environ.get('KIENZLEDOKU_CONFIG_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ['LOCALAPPDATA']) / 'kienzledoku record'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Kienzledoku'
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'kienzledoku'


def config_path():
    return config_dir() / 'config.toml'


def defaults():
    return {
        'connection': {'mode': 'direct', 'target': 'https://127.0.0.1:16567/aps/fhir/api/r4',
                       'ca_file': '', 'allow_insecure_tls': False},
        'commander': {'enabled': True, 'url': 'http://127.0.0.1:8185',
                      'token_env': 'KIENZLEDOKU_COMMANDER_TOKEN',
                      'token_file': '', 'request_timeout': 2400,
                      'default_quality': 'auto'},
        'services': {'asr': 'http://127.0.0.1:8179', 'diarization': 'http://127.0.0.1:8183',
                     'llm': 'http://127.0.0.1:8080'},
        'record': {'diarization': True, 'microphone': '', 'output_mode': 'structured', 'single_code': 'KI'},
    }


def validate(config):
    expected = defaults()
    if set(config) != set(expected):
        raise ValueError('Unbekannte oder fehlende Konfigurationsabschnitte')
    for section, values in expected.items():
        if set(config[section]) != set(values):
            raise ValueError('Unbekannte oder fehlende Einstellungen: ' + section)
        for key, value in values.items():
            if type(config[section][key]) is not type(value):
                raise ValueError('Ungültiger Wert: ' + section + '.' + key)
    connection = config['connection']
    commander = config['commander']
    for address in [connection['target'], commander['url']] + list(config['services'].values()):
        if any(ord(char) < 32 for char in address):
            raise ValueError('Ungültiges Steuerzeichen in einer Adresse')
    if connection['mode'] not in ('direct', 'connect'):
        raise ValueError('Betriebsart muss direct oder connect sein')
    target = urllib.parse.urlsplit(connection['target'])
    if (target.scheme != 'https' or not target.hostname or target.username is not None
            or target.query or target.fragment or target.path.rstrip('/') != '/aps/fhir/api/r4'
            or '%' in target.path or '\\' in connection['target']):
        raise ValueError('T2med benötigt ein genaues HTTPS-Ziel mit /aps/fhir/api/r4')
    _ = target.port
    for value in config['services'].values():
        parsed = urllib.parse.urlsplit(value)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or not parsed.port
                or parsed.username is not None or parsed.query or parsed.fragment):
            raise ValueError('Dienstadresse benötigt http(s)://Host:Port ohne Zugangsdaten')
    commander_url = urllib.parse.urlsplit(commander['url'])
    if (commander_url.scheme not in ('http', 'https') or not commander_url.hostname
            or not commander_url.port or commander_url.path not in ('', '/')
            or commander_url.username is not None or commander_url.query or commander_url.fragment):
        raise ValueError('Commander-Adresse benötigt http(s)://Host:Port ohne Zugangsdaten')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', commander['token_env']):
        raise ValueError('Ungültige Commander-Tokenvariable')
    if commander['token_file'] and not Path(commander['token_file']).expanduser().is_absolute():
        raise ValueError('Commander-Tokendatei benötigt einen absoluten Pfad')
    if not 30 <= commander['request_timeout'] <= 7200:
        raise ValueError('Commander-Zeitgrenze muss zwischen 30 und 7200 Sekunden liegen')
    quality = commander['default_quality']
    if quality != 'auto' and not re.fullmatch(r'[a-z0-9][a-z0-9_]{0,63}', quality):
        raise ValueError('Ungültige Commander-Standardqualität')
    if config['record']['output_mode'] not in ('structured', 'single'):
        raise ValueError('Ungültiges Dokumentationsformat')
    code = config['record']['single_code']
    if not code.strip() or len(code) > 20 or any(ord(c) < 32 for c in code):
        raise ValueError('Kürzel benötigt 1 bis 20 druckbare Zeichen')
    return config


def load(path=None):
    path = Path(path or config_path())
    result = defaults()
    if path.exists():
        # Commander is opt-in for configurations created by earlier clients.
        # Fresh installations use the enabled default above.
        result['commander']['enabled'] = False
        if path.suffix == '.json':
            old = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(old, dict):
                raise ValueError('Alte Konfiguration ist kein JSON-Objekt')
            result['services'].update(old.get('services', {}))
            if 'commander' in old:
                if not isinstance(old['commander'], dict):
                    raise ValueError('Commander-Konfiguration ist ungültig')
                result['commander'].update(old['commander'])
            host = old.get('t2med', {}).get('fhir_host', '127.0.0.1')
            if ':' in host and not host.startswith('['):
                host = '[' + host + ']'
            result['connection']['target'] = 'https://%s:16567/aps/fhir/api/r4' % host
            # Preserve the previous installation-specific APS TLS behaviour.
            result['connection']['allow_insecure_tls'] = True
        else:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            data = tomllib.loads(path.read_text(encoding='utf-8'))
            for section, values in data.items():
                if section not in result or not isinstance(values, dict):
                    raise ValueError('Unbekannter Konfigurationsabschnitt')
                result[section].update(values)
    elif path == config_path() and path.with_suffix('.json').exists():
        result = load(path.with_suffix('.json'))
    return validate(result)


def save(config, path=None):
    validate(config)
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = ['# kienzledoku record 1.3.3 — keine Zugangsdaten/Patienten in dieser Datei.']
    for section, values in config.items():
        lines.extend(['', '[' + section + ']'])
        for name, value in values.items():
            rendered = ('true' if value else 'false') if isinstance(value, bool) else json.dumps(value, ensure_ascii=False)
            lines.append(name + ' = ' + rendered)
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix='.config-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('\n'.join(lines) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def target_identity(raw):
    u = urllib.parse.urlsplit(raw)
    return (u.scheme.lower(), (u.hostname or '').lower(), u.port or 443, u.path.rstrip('/'))


def initialize_installation():
    """Keep legacy/current settings; honor existing installer preseeds only when fresh."""
    cfg = load()
    if not config_path().exists() and not config_path().with_suffix('.json').exists():
        def host_url(host, port, scheme='http'):
            if ':' in host and not host.startswith('['): host = '[' + host + ']'
            return '%s://%s:%s' % (scheme, host, port)
        for name, port in (('asr', '8179'), ('diarization', '8183'), ('llm', '8080')):
            prefix = 'KIENZLEDOKU_INSTALL_' + name.upper()
            cfg['services'][name] = host_url(os.environ.get(prefix + '_HOST', '127.0.0.1'), os.environ.get(prefix + '_PORT', port))
        host = os.environ.get('KIENZLEDOKU_INSTALL_T2MED_HOST')
        if host:
            cfg['connection']['target'] = host_url(host, '16567', 'https') + '/aps/fhir/api/r4'
    save(cfg)


def validate_target(raw, config):
    candidate = copy.deepcopy(config)
    candidate['connection']['target'] = raw
    validate(candidate)
    if target_identity(raw) != target_identity(config['connection']['target']):
        raise ValueError('Das T2med-Ziel stimmt nicht mit den Einstellungen überein. Bitte Einstellungen prüfen.')


def ssl_context(connection):
    ctx = ssl.create_default_context(cafile=connection.get('ca_file') or None)
    if connection.get('allow_insecure_tls'):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _windows_crypt(value, protect):
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    fn = getattr(ctypes.windll.crypt32, 'CryptProtectData' if protect else 'CryptUnprotectData')
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('Windows-Zugangsdaten konnten nicht verarbeitet werden')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def read_windows_key():
    if sys.platform != 'win32':
        return ''
    path = config_dir() / 'direct-key.dpapi'
    if path.exists():
        return _windows_crypt(path.read_bytes(), False).decode('utf-8')
    return ''


def read_commander_token():
    """Read the Commander token without placing it in TOML or process arguments."""
    if sys.platform == 'win32':
        path = config_dir() / 'commander-token.dpapi'
        if path.exists():
            return _windows_crypt(path.read_bytes(), False).decode('utf-8')
        return ''
    path = config_dir() / 'commander.token'
    if not path.exists():
        return ''
    info = path.lstat()
    getuid = getattr(os, 'getuid', None)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Commander-Tokendatei ist nicht privat (0600)')
    if callable(getuid) and info.st_uid != getuid():
        raise ValueError('Commander-Tokendatei gehört nicht dem aktuellen Benutzer')
    value = path.read_text(encoding='utf-8').strip()
    if not value or len(value) > 4096 or any(char.isspace() for char in value):
        raise ValueError('Commander-Token ist ungültig')
    return value


def store_commander_token(token):
    if not token or len(token) > 4096 or any(char.isspace() for char in token):
        raise ValueError('Ungültiger Commander-Token')
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == 'win32':
        (directory / 'commander-token.dpapi').write_bytes(_windows_crypt(token.encode('utf-8'), True))
        return
    os.chmod(str(directory), 0o700)
    path = directory / 'commander.token'
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            fd = -1
            handle.write(token + '\n')
    finally:
        if fd >= 0:
            os.close(fd)


def store_direct_key(key):
    if not key or '\n' in key or '\r' in key:
        raise ValueError('Ungültiger API-Key')
    if sys.platform == 'win32':
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / 'direct-key.dpapi').write_bytes(_windows_crypt(key.encode('utf-8'), True))
    elif sys.platform == 'darwin':
        # security's interactive input keeps the secret off the process argv.
        import shlex
        import getpass
        command = 'add-generic-password -U -s Kienzledoku-T2med-API-Key -a ' + shlex.quote(getpass.getuser()) + ' -w ' + shlex.quote(key) + '\n'
        proc = subprocess.run(['/usr/bin/security', '-i'], input=command, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode:
            raise RuntimeError('API-Key konnte nicht im Schlüsselbund gespeichert werden')
    else:
        proc = subprocess.run(['secret-tool', 'store', '--label=kienzledoku record T2med',
                               'application', 'kienzledoku', 'service', 't2med-api-key'],
                              input=key, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode:
            raise RuntimeError('API-Key konnte nicht im Schlüsselbund gespeichert werden')
