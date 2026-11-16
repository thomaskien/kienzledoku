"""Reproduce reviewed Python 3.12 server locks; updating them is explicit."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'macos': ('aarch64-apple-darwin', '# Python 3.12; macOS 14+ arm64\n'),
    'linux': ('x86_64-unknown-linux-gnu', '# Python 3.12; Ubuntu 24.04 x86_64\n'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uv', default='uv')
    parser.add_argument('--write', action='store_true', help='Replace both copies; review their diff afterwards.')
    args = parser.parse_args()
    if subprocess.check_output([args.uv, '--version'], text=True).split()[:2] != ['uv', '0.13.8']:
        raise ValueError('Lock-Erzeugung benötigt uv 0.13.8.')
    directory = ROOT/'installer/dependency-locks'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('UV_', 'PIP_'))}
    if 'UV_CACHE_DIR' in os.environ:
        env['UV_CACHE_DIR'] = os.environ['UV_CACHE_DIR']
    env['MACOSX_DEPLOYMENT_TARGET'] = '14.0'
    with tempfile.TemporaryDirectory(prefix='kienzledoku-locks-') as tmp:
        for platform, (target, header) in TARGETS.items():
            for role in ('asr', 'diar'):
                name = f'{platform}-{role}-py312.txt'
                output = Path(tmp)/name
                subprocess.run([args.uv, '--no-config', 'pip', 'compile',
                    str(directory/f'inputs-{platform}-{role}.in'),
                    '--python-version', '3.12', '--python-platform', target,
                    '--default-index', 'https://pypi.org/simple', '--only-binary', ':all:',
                    '--generate-hashes', '--no-header', '--no-annotate', '-o', str(output)],
                    env=env, stdout=subprocess.DEVNULL, check=True)
                data = (header + '--index-url https://pypi.org/simple\n' + output.read_text()).encode()
                copies = (directory/name, ROOT/'server-windows/linux/dependency-locks'/name)
                for path in copies:
                    if args.write:
                        path.write_bytes(data)
                    elif path.read_bytes() != data:
                        raise ValueError('Lock-Differenz; vor Übernahme prüfen: '+str(path))
                print(name + ': ' + ('geschrieben' if args.write else 'identisch'), flush=True)


if __name__ == '__main__':
    main()
