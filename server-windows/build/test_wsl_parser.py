#!/usr/bin/env python3
"""Exercise actual emitted command lines against Microsoft's portable parser body."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pwsh',required=True)
    args=parser.parse_args()
    records=json.loads(subprocess.check_output([args.pwsh,'-NoLogo','-NoProfile','-File',str(ROOT/'tests/export_native_arguments.ps1')],text=True))
    with tempfile.TemporaryDirectory(prefix='kienzledoku-wsl-parser-') as temp:
        binary=Path(temp)/'wsl-parser'
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(ROOT/'tests/fixtures/wsl_parse_argument.cpp'),'-o',str(binary)],check=True)
        def token(raw,quotes=False):
            return subprocess.check_output([str(binary),raw,str(int(quotes))],text=True)
        for record in records:
            expected=record['Arguments'][0]
            if token(record['PreviousRaw'])==expected:
                raise AssertionError('Prior quoting problem not reproduced: '+record['Name'])
            if token(record['Raw'])!=expected:
                raise AssertionError('Emitted command not recognized by Microsoft WSL parser: '+record['Name'])
            print('PASS '+record['Name']+': previous quoted switch rejected; corrected switch recognized')
        record=next(r for r in records if r['Name']=='import')
        if '"C:\\Users\\Test User\\Server\\wsl"' not in record['Raw'] or '"C:\\Cache Files\\ubuntu.wsl"' not in record['Raw']:
            raise AssertionError('Spaced import paths lost quoting')
        print('PASS import paths retain required quotes')
        raw='"C:\\Users\\Test User\\Server\\wsl" remaining'
        if token(raw,True)!='"C:\\Users\\Test User\\Server\\wsl"':
            raise AssertionError('Quoted path parsing fixture incorrect')
        print('PASS upstream HandleQuotes path parsing preserves spaced values')
        report={'version':(ROOT/'VERSION').read_text().strip(),'cases_passed':9,'previous_quoting_failure_reproduced':True,
                'fixture':'Microsoft WSL ParseArgument body compiled and executed on Linux',
                'command_lines':'actual ConvertTo-NativeArguments PowerShell function output',
                'windows_runtime_tested':False,'records':records}
        (ROOT/'evidence/wsl-argument-parser.json').write_text(json.dumps(report,indent=2)+'\n')
    print('All 9 parser compatibility cases passed; this does not execute Windows/WSL.')

if __name__=='__main__':main()
