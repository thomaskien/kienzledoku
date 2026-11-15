"""Exercise two real installer payloads in an isolated home, without user services.

Usage: python verify_macos_client_upgrade.py OLD_PAYLOAD NEW_PAYLOAD EMPTY_WORKDIR
Uses unique test bundle IDs/URL schemes; no real application is launched.
"""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tomllib
from unittest import mock

LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def install(payload, work):
    sys.path.insert(0, str(payload))
    from installer import core, update_macos
    import kienzledoku_config as record
    home = work / 'home'
    home.mkdir(exist_ok=True)
    support = work / 'support'
    hw = dict(platform='darwin', arch='arm64', ram_gib=32, free_gib=100,
              server_supported=True)
    installer = core.Installer(support, hw)
    identifiers = {role: 'de.kienzledoku.upgradetest.' + work.name + '.' + role
                   for role in ('record', 'connect')}
    if not (support / 'config.toml').exists():
        cfg = record.load(support / 'config.toml')
        cfg['connection']['mode'] = os.environ.get('KIENZLEDOKU_TEST_CONNECTION_MODE', 'direct')
        cfg['record'].update(vad_enabled=False, silence_threshold_dbfs=-43)
        record.save(cfg, support / 'config.toml')
        (support / 'commander.token').write_text('synthetic-update-token')
        (support / 'models').mkdir()
        (support / 'models/synthetic.gguf').write_bytes(b'synthetic preserved model')
    before = tomllib.loads((support / 'config.toml').read_text())['record']
    connection_before = tomllib.loads((support / 'config.toml').read_text())['connection']
    original_app = installer._app

    def isolated_app(*args):
        app, destination = original_app(*args)
        info_path = app / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        role = args[2]
        info['CFBundleIdentifier'] = identifiers[role]
        info['CFBundleURLTypes'] = [dict(CFBundleURLSchemes=[work.name + '-' + role])]
        info_path.write_bytes(plistlib.dumps(info))
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        return app, destination

    # Real file copies, offline pip, binaries, signatures and Launch Services;
    # only home and test app identities differ from a normal client installation.
    with mock.patch.object(Path, 'home', return_value=home), \
         mock.patch.dict(update_macos.APP_IDS, identifiers), \
         mock.patch.object(installer, '_app', side_effect=isolated_app):
        cfg = core.defaults(hw, support)
        cfg.update(mode='client', commander_url='http://192.0.2.123:8185',
                   commander_token='synthetic-update-token')
        installer._work(cfg)
        state = installer.snapshot()
        if not state['done']:
            raise AssertionError(state['error'])
        roots = update_macos.component_versions(support, home)
    assert len(set(roots.values())) == 1
    active = roots['record']
    assert list((support / 'versions').iterdir()) == [active]
    assert active.name.startswith(core.VERSION + '-')
    assert not list(active.glob('*-previous.app'))
    after = tomllib.loads((support / 'config.toml').read_text())['record']
    assert tomllib.loads((support / 'config.toml').read_text())['connection'] == connection_before
    if (payload / 'LICENSE').is_file():
        assert (active / 'LICENSE').read_bytes() == (payload / 'LICENSE').read_bytes()
    assert after['vad_enabled'] == before['vad_enabled'] == False
    assert after['silence_threshold_dbfs'] == before['silence_threshold_dbfs'] == -43
    assert (support / 'commander.token').read_text() == 'synthetic-update-token'
    assert (support / 'models/synthetic.gguf').read_bytes() == b'synthetic preserved model'
    env = dict(os.environ, KIENZLEDOKU_CONFIG_DIR=str(support), PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([str(active / 'venv/bin/python'), str(active / 'kienzledoku.py'), '--self-test'], check=True, env=env)
    return dict(version=core.VERSION, active=str(active), passed=True)


if __name__ == '__main__':
    if sys.argv[1] == '--phase':
        payload, work = map(lambda s: Path(s).resolve(), sys.argv[2:4])
        result = install(payload, work)
        (work / ('phase-' + result['version'] + '.json')).write_text(json.dumps(result))
        print('Real isolated Mac client install passed:', result['version'])
    else:
        old, new, work = map(lambda s: Path(s).resolve(), sys.argv[1:4])
        work.mkdir(exist_ok=False)
        try:
            for payload in (old, new):
                subprocess.run([sys.executable, __file__, '--phase', str(payload), str(work)], check=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            print('PASS: native isolated client upgrade, old-tree cleanup, settings/token/model retention')
        finally:
            for app in (work / 'home/Applications').glob('*.app'):
                subprocess.run([LSREGISTER, '-u', str(app)], check=False, capture_output=True)
