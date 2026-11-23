"""Start the shipped Record client with its private packages and external CPython."""
import os
import platform
import runpy
import sys
from pathlib import Path


def main():
    if (sys.platform != 'darwin' or sys.implementation.name != 'cpython'
            or sys.version_info[:2] != (3, 12) or platform.machine() not in ('arm64', 'x86_64')):
        raise SystemExit('KienzleDoku benötigt CPython 3.12 für Ihren Mac.')
    resources = Path(__file__).resolve().parent
    payload = resources / 'payload'
    os.environ['KIENZLEDOKU_UNIFIED_CLIENT'] = '1'
    sys.path[:0] = [str(payload), str(resources / 'vendor' / platform.machine())]
    runpy.run_path(str(payload / 'kienzledoku.py'), run_name='__main__')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.exit(70)
