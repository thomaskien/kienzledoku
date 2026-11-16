"""Fail builds if shared sources drift outside the reviewed platform differences."""
import difflib
import json
from pathlib import Path


def difference(left, right):
    return ''.join(line for line in difflib.unified_diff(left.splitlines(True), right.splitlines(True), n=3)
                   if not line.startswith(('---', '+++', '@@')))


def check(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    base = root/'kienzledoku_commander'
    runtime = root/'server-windows/linux/runtime/kienzledoku_commander'
    allowed = json.loads((root/'installer/runtime-variants.json').read_text())
    left = {p.name for p in base.glob('*.py')}
    right = {p.name for p in runtime.glob('*.py')}
    if right-left != {'asr_stage.py'} or left-right:
        raise ValueError('Nicht zugeordnete Commander-Module')
    errors = []
    for name in sorted(left):
        actual = difference((base/name).read_text(), (runtime/name).read_text())
        if actual != allowed.get(name, {}).get('diff', ''):
            errors.append(name)
    pairs = [(root/'kienzledoku_document.py', runtime.parent/'kienzledoku_document.py'),
             (root/'installer/locked_dependencies.py', runtime.parent.parent/'locked_dependencies.py')]
    pairs += [(p, runtime.parent.parent/'dependency-locks'/p.name) for p in (root/'installer/dependency-locks').glob('*.txt')]
    if {p.name for p in (root/'installer/dependency-locks').glob('*.txt')} != {p.name for p in (runtime.parent.parent/'dependency-locks').glob('*.txt')}:
        errors.append('dependency-locks/dateiliste')
    for left_path, right_path in pairs:
        if left_path.read_bytes() != right_path.read_bytes(): errors.append(str(left_path.relative_to(root)))
    if errors:
        raise ValueError('Nicht freigegebene Unterschiede der Auslieferungsvarianten: '+', '.join(errors))
    return dict(common_modules=len(left), reviewed_variants=sorted(allowed), runtime_only=['asr_stage.py'], status='passed')


if __name__ == '__main__':
    print(json.dumps(check(), sort_keys=True))
