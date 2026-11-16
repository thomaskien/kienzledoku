"""Run each suite in its own process with a verified package origin."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant',choices=('client','runtime'))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    cwd=root if args.variant=='client' else root/'server-windows/linux/runtime'
    tests=root/'tests' if args.variant=='client' else root/'server-windows/tests'
    code='''import pathlib, sys, unittest
import kienzledoku_commander
expected=pathlib.Path.cwd()/"kienzledoku_commander/__init__.py"
actual=pathlib.Path(kienzledoku_commander.__file__).resolve()
print("Commander-Testursprung:", actual, flush=True)
assert actual == expected.resolve(), "Falscher Commander-Codebaum"
suite=unittest.defaultTestLoader.discover(sys.argv[1])
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''
    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if args.variant=='runtime': env['KIENZLEDOKU_COMMANDER_TOKEN']='synthetic-audit-regression-token'
    else: env.pop('KIENZLEDOKU_COMMANDER_TOKEN',None)
    env.pop('PYTHONPATH',None)
    return subprocess.run([sys.executable,'-B','-c',code,str(tests)],cwd=cwd,env=env).returncode


if __name__ == '__main__': sys.exit(main())
