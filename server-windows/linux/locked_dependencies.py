"""Install and inventory the complete, hash-pinned Python server environments."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path):
    raw = Path(path).read_bytes()
    packages = {}
    for line in raw.decode("utf-8").replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--index-url ", "--extra-index-url ")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:==([^\s]+)|\s+@\s+(\S+))\s+((?:--hash=sha256:[0-9a-f]{64}\s*)+)", line)
        if not match or canonical(match[1]) in packages:
            raise ValueError("Ungültiger oder unvollständiger Dependency-Lock: " + Path(path).name)
        version, source = match[2], match[3]
        if source:
            url = urlsplit(source)
            filename = unquote(url.path).rsplit('/', 1)[-1]
            parts = filename.split('-')
            if (url.scheme != 'https' or url.hostname not in {'download.pytorch.org', 'download-r2.pytorch.org'} or url.username or url.query
                    or not filename.endswith('.whl') or len(parts) != 5 or canonical(parts[0]) != canonical(match[1])):
                raise ValueError('Ungültige feste Wheel-Quelle')
            version = parts[1]
        packages[canonical(match[1])] = {"version": version, "approved_sha256": re.findall(r"sha256:([0-9a-f]{64})", match[4])}
        if source: packages[canonical(match[1])]['source'] = source
    if not packages:
        raise ValueError("Leerer Dependency-Lock")
    return hashlib.sha256(raw).hexdigest(), packages


SNAPSHOT = '''import importlib.metadata as m, json, platform, re, sys
packages = {}
for d in m.distributions():
    name = re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower()
    if name in packages: raise RuntimeError("Doppelte Paketinstallation: " + name)
    packages[name] = d.version
print(json.dumps(dict(python=list(sys.version_info[:2]), platform=sys.platform,
                     machine=platform.machine(), packages=packages)))
'''


def snapshot(python):
    return json.loads(subprocess.check_output([str(python), "-I", "-c", SNAPSHOT], text=True))


def verify_target(state, lock_name):
    target = ("darwin", "arm64") if lock_name.startswith("macos-") else ("linux", "x86_64")
    if state["python"] != [3, 12] or (state["platform"], state["machine"]) != target:
        raise ValueError("Dependency-Lock passt nicht zu Python 3.12 und der Zielplattform: " + lock_name)


def verify_snapshot(state, packages, lock_name):
    verify_target(state, lock_name)
    actual = {name: value for name, value in state["packages"].items() if name not in {"pip", "wheel", "setuptools"} or name in packages}
    expected = {name: item["version"] for name, item in packages.items()}
    if actual != expected:
        raise ValueError("Installierter Paketstand weicht vom Dependency-Lock ab.")


def install_locked(python, lock, report, run, env=None):
    """run must execute a checked command. Only this dedicated venv is affected.

    Old packages-1.0 stamps are deliberately not consulted. The inventory is
    rechecked even when a matching lock digest was installed before.
    """
    lock, report = Path(lock), Path(report)
    digest, packages = read_lock(lock)
    previous = {}
    if report.is_file():
        try:
            previous = json.loads(report.read_text())
        except (OSError, ValueError):
            pass
    state = snapshot(python)
    verify_target(state, lock.name)
    reusable = previous.get("lock_sha256") == digest
    try:
        verify_snapshot(state, packages, lock.name)
    except ValueError:
        reusable = False
    if not reusable:
        # Force verification of artifact hashes when adopting an old/unverified venv.
        run([python, "-m", "pip", "--isolated", "install", "--require-hashes",
             "--only-binary=:all:", "--no-input", "--disable-pip-version-check",
             "--force-reinstall", "-r", lock], env=env)
        state = snapshot(python)
        verify_snapshot(state, packages, lock.name)
    run([python, "-m", "pip", "--isolated", "check"], env=env)
    value = dict(schema=1, lock=lock.name, lock_sha256=digest,
                 python=state["python"], platform=state["platform"], machine=state["machine"],
                 distributions=packages, dependency_check="passed")
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(report.suffix + ".new")
    with temporary.open("w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(report)
    return value
