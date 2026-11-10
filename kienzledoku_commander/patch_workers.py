"""SHA-256-gesicherte, reversible Hooks für die geprüften Linux-Worker."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

HASHES = {
    "whisper": "bd80dddcffb1e24782508adeac17f1b91b3ef4b819a59035769985ae968f4412",
    "diar": "b4d35c393ead5a917740a1bf71a607b2494fb83075636cd88d814dcb1a8893ac",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def transform(role, raw):
    text = raw.decode("utf-8")
    tree = ast.parse(text)
    if "kienzledoku_commander.worker" in text:
        raise ValueError("Hook bereits vorhanden; Manifest prüfen.")
    lines = text.splitlines(keepends=True)
    changes = []
    if role == "whisper":
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"]
        apps = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "app" for t in n.targets)]
        if len(functions) != 1 or len(apps) != 1:
            raise ValueError("Unbekannte Whisper-Struktur")
        yields = [n for n in functions[0].body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield)]
        if len(yields) != 1 or yields[0] is not functions[0].body[-1]:
            raise ValueError("Unbekannter Worker-Lebenszyklus")
        y = yields[0]
        changes.append((y.lineno - 1, y.end_lineno,
            "    commander_control = start_whisper_control(app, transcription_engine)\n"
            "    try:\n        yield\n    finally:\n        close_control(commander_control)\n"))
        changes.append((apps[0].end_lineno, apps[0].end_lineno,
            "app.add_middleware(WhisperGateMiddleware)\n"))
        imports = "from kienzledoku_commander.worker import start_whisper_control, close_control, WhisperGateMiddleware\n"
    elif role == "diar":
        mains = [n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) in ("__name__ == '__main__'", "'__main__' == __name__")]
        if len(mains) != 1 or not mains[0].body:
            raise ValueError("Unbekannter Diarisierungsstart")
        at = mains[0].body[0].lineno - 1
        changes.append((at, at, "    commander_control = start_diar_control(globals())\n"))
        imports = "from kienzledoku_commander.worker import start_diar_control\n"
    else:
        raise ValueError("Unbekannter Worker")
    # Preserve module docstring and mandatory future-import placement.
    at = 0
    for node in tree.body:
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)) or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            at = node.end_lineno
        else:
            break
    changes.append((at, at, imports))
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = [replacement]
    result = "".join(lines).encode()
    compile(result, "worker-with-commander", "exec")
    return result


def atomic_write(path, data, metadata):
    fd, temporary = tempfile.mkstemp(prefix=".commander-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), metadata["mode"])
            if os.geteuid() == 0:
                os.fchown(f.fileno(), metadata["uid"], metadata["gid"])
        if "mtime_ns" in metadata:
            os.utime(temporary, ns=(metadata["atime_ns"], metadata["mtime_ns"]))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_manifest(backup):
    manifest = json.loads((backup / "manifest.json").read_text())
    if set(manifest) != {"whisper", "diar"}:
        raise ValueError("Unvollständiges Sicherungsmanifest")
    for role, item in manifest.items():
        original = (backup / (role + ".original")).read_bytes()
        if digest(original) != item["before"]:
            raise ValueError("Sicherung ist beschädigt")
    return manifest


def rollback(backup):
    backup = Path(backup)
    manifest = validate_manifest(backup)
    # Validate every target before restoring any target.
    for item in manifest.values():
        p = Path(item["path"])
        if p.is_symlink() or digest(p.read_bytes()) not in (item["before"], item["after"]):
            raise ValueError("Worker wurde zwischenzeitlich verändert; Rollback abgebrochen.")
    for role, item in manifest.items():
        atomic_write(Path(item["path"]), (backup / (role + ".original")).read_bytes(), item)


def apply(paths, backup, expected=None, check=False):
    expected = HASHES if expected is None else expected
    backup = Path(backup)
    if set(paths) != set(HASHES):
        raise ValueError("Beide Worker werden benötigt")
    if (backup / "manifest.json").exists():
        manifest = validate_manifest(backup)
        if all(str(Path(paths[r]).resolve()) == item["path"] and digest(Path(paths[r]).read_bytes()) == item["after"] for r, item in manifest.items()):
            return "bereits installiert"
    plans, manifest = {}, {}
    for role, filename in paths.items():
        p = Path(filename)
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode) or p.is_symlink():
            raise ValueError("Worker muss eine reguläre Datei sein")
        original = p.read_bytes()
        if digest(original) != expected[role]:
            raise ValueError("Unbekannte SHA-256-Ausgangsdatei: " + role)
        patched = transform(role, original)
        plans[role] = (original, patched)
        manifest[role] = {"path": str(p.resolve()), "before": digest(original), "after": digest(patched),
                          "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
                          "atime_ns": info.st_atime_ns, "mtime_ns": info.st_mtime_ns}
    if check:
        return "beide Originaldateien geprüft"
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    for role, (original, _) in plans.items():
        atomic_write(backup / (role + ".original"), original, {"mode": 0o600, "uid": os.getuid(), "gid": os.getgid()})
    atomic_write(backup / "manifest.json", json.dumps(manifest, indent=2).encode(), {"mode": 0o600, "uid": os.getuid(), "gid": os.getgid()})
    try:
        for role, (_, patched) in plans.items():
            atomic_write(Path(manifest[role]["path"]), patched, manifest[role])
    except BaseException:
        rollback(backup)
        raise
    return "Hooks installiert; Worker noch nicht neu gestartet"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--whisper")
    parser.add_argument("--diar")
    parser.add_argument("--backup", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        if args.rollback:
            rollback(args.backup)
            print("Originaldateien wiederhergestellt; Worker neu starten.")
        else:
            if not args.whisper or not args.diar:
                parser.error("--whisper und --diar sind erforderlich")
            print(apply({"whisper": args.whisper, "diar": args.diar}, args.backup, check=args.check))
    except (ValueError, OSError, KeyError):
        parser.exit(1, "Worker-Patch abgebrochen: Originaldateien und Sicherungsmanifest prüfen.\n")


if __name__ == "__main__":
    main()
