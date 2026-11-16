# Python-Serverabhängigkeiten

Die vier Locks umfassen direkte und transitive Python-Abhängigkeiten für
Python 3.12: macOS 14+ auf Apple Silicon sowie Ubuntu 24.04 x86_64 unter Linux
oder WSL. ASR und Sprechertrennung verwenden getrennte virtuelle Umgebungen.

Der Ausgangsstand wurde am 16.11.2026 aus den Paketmetadaten der vorhandenen
Mac- und Linux-Installation gelesen, ohne Modelle zu laden oder Dienste zu
ändern. Alle 36/94 Mac- und 86/113 Linux-Paketversionen wurden übernommen.
`pip` ist das Installationswerkzeug und gehört nicht zum Runtime-Paketinventar.
Modelle, Python-Distribution, llama.cpp und Betriebssystempakete haben eigene
Quellen und Prüfungen; diese Dateien sind kein vollständiger Betriebssystem-SBOM.

Die `inputs-*.in` enthalten auch die transitiven Versionsvorgaben. PyTorch und
torchaudio unter Linux verweisen auf feste offizielle CUDA-Wheels. Die übrigen
Pakete kommen von PyPI. Die Lock-Dateien enthalten erlaubte Artefakt-Hashes;
der Installer akzeptiert nur Wheels und prüft jeden Download per SHA-256.
Die Linux-Auslieferung enthält identische Kopien unter
`server-windows/linux/dependency-locks`; die Buildprüfung erzwingt Gleichheit.

## Reproduzieren und aktualisieren

Mit `uv 0.13.8` prüft folgender Befehl alle vier Locks, ohne sie zu ändern:

```bash
python3.12 installer/compile_dependency_locks.py --uv /pfad/zu/uv
```

Bei einer beabsichtigten Abhängigkeitsänderung zuerst die Eingaben bearbeiten,
dann mit `--write` beide Lock-Kopien erzeugen und den Diff prüfen. Neue oder
nachträglich hinzugefügte Wheel-Hashes sind ebenfalls Änderungen, die geprüft
werden müssen. Anschließend zwei frische Zielumgebungen installieren,
`pip check`, Modellstart und synthetische Audioverarbeitung auf der jeweiligen
Hardware prüfen. Der Compiler ersetzt diese Laufzeitabnahme nicht.

## Installation und Inventar

`locked_dependencies.py` prüft vor Änderungen Python und Zielplattform.
Ein alter `packages-1.0`-Stempel hat keine Freigabewirkung. Die erste Übernahme
installiert die festgelegten Wheels mit Hashprüfung erneut. Spätere Durchläufe
prüfen den Lock-Digest und die tatsächlich installierten Versionen einschließlich
zusätzlicher Pakete. `pip check` muss erfolgreich sein. Ein abweichender
Paketbestand führt zur Neuinstallation beziehungsweise zum Abbruch, falls sich
der Sollbestand nicht herstellen lässt.

Erst nach erfolgreicher Prüfung wird atomar ein privates JSON-Inventar mit
Lock-Digest, Zielplattform, Paketversionen und erlaubten Artefakt-Hashes geschrieben.
macOS: `asr-dependencies.json` und `diar-dependencies.json` im Versionsverzeichnis.
Linux/WSL: `asr-dependencies.json` und `diarization-dependencies.json` im
Installer-State-Verzeichnis. Diese Dateien enthalten keine Audio-, Patienten-,
Token- oder Dokumentationsdaten und können als Softwareinventar exportiert werden.
Die Hashliste benennt zulässige Paketartefakte, nicht einen nachträglichen Hash
aller installierten Dateien. Die gesondert geprüften Worker-Patches bleiben nötig.
