"""Check the staged Windows Python dependency closure, without loading native DLLs.

Run with the build-host Python. The staged pure-Python packaging package evaluates
Windows markers explicitly, so the cross-build host's platform cannot hide gaps.
"""
import argparse
from email.parser import Parser
import json
from pathlib import Path
import sys


def check(site, python_version):
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    from packaging.version import Version

    environment = default_environment()
    environment.update(os_name='nt', sys_platform='win32', platform_system='Windows',
                       platform_machine='AMD64', platform_release='10', platform_version='10.0',
                       python_version='.'.join(python_version.split('.')[:2]),
                       python_full_version=python_version, implementation_name='cpython',
                       implementation_version=python_version, platform_python_implementation='CPython',
                       extra='')
    installed = {}
    for path in sorted(site.glob('*.dist-info/METADATA')):
        metadata = Parser().parsestr(path.read_text(encoding='utf-8'))
        name = canonicalize_name(metadata['Name'])
        if name in installed:
            raise ValueError('Doppelte Windows-Python-Abhängigkeit: ' + name)
        installed[name] = metadata
    if not installed:
        raise ValueError('Keine Windows-Python-Pakete im Prüfverzeichnis.')
    extras = {name: {''} for name in installed}
    errors = set()
    pending = set(installed)
    while pending:
        name = pending.pop()
        metadata = installed[name]
        minimum = metadata.get('Requires-Python')
        if minimum and Version(python_version) not in SpecifierSet(minimum):
            errors.add(f'{name}: Python {python_version} erfüllt {minimum} nicht')
        for declared in metadata.get_all('Requires-Dist', []):
            requirement = Requirement(declared)
            if requirement.marker and not any(
                requirement.marker.evaluate(dict(environment, extra=extra)) for extra in extras[name]
            ):
                continue
            target = canonicalize_name(requirement.name)
            if target not in installed:
                errors.add(f'{name}: {requirement} fehlt')
                continue
            if requirement.url:
                errors.add(f'{name}: direkte URL-Abhängigkeit muss gesondert geprüft werden: {target}')
            if Version(installed[target]['Version']) not in requirement.specifier:
                errors.add(f'{name}: {requirement} passt nicht zu {installed[target]["Version"]}')
            new_extras = set(requirement.extras) - extras[target]
            if new_extras:
                extras[target].update(new_extras)
                pending.add(target)
    if errors:
        raise ValueError('Windows-Python-Abhängigkeiten unvollständig:\n' + '\n'.join(sorted(errors)))
    return dict(platform='win_amd64', python=python_version, dependency_closure=True,
                distributions={name: installed[name]['Version'] for name in sorted(installed)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-packages', type=Path, required=True)
    parser.add_argument('--python-version', required=True)
    args = parser.parse_args()
    # Only packaging (pure Python) is imported from the hash-verified payload.
    sys.path.insert(0, str(args.site_packages.resolve()))
    print(json.dumps(check(args.site_packages, args.python_version), sort_keys=True))
