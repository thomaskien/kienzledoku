# Auditkorrekturen in 1.8

- **A01:** Fachlicher Abschluss und Wiederholungssperre nach bestätigter
  T2med-Speicherung vor jeder Fensterausgabe. Eine fehlgeschlagene Ausgabe setzt
  diese nicht zurück; tatsächlich ungewisse Schreibausgänge bleiben gesperrt.
- **A02:** Linux/WSL dekodiert PCM16-WAV mono/16 kHz direkt aus dem Request im RAM.
  Es entsteht keine temporäre WAV-Datei, auch nicht vor einem harten Prozessabbruch.
  Damit ist für diesen Pfad auch keine RAM-Disk-Datei nötig. Betriebssystem-Swap
  und Crashdumps sind davon unabhängig; keine Zusage physisch gesperrter RAM-Seiten.
- **A05:** `PYANNOTE_METRICS_ENABLED=0` vor Import, Start und Modellvorbereitung,
  einschließlich Migration bekannter älterer Worker-Patches.
- **A06:** Genau ein eindeutig zugeordneter Patient. Mehrdeutige/widersprüchliche
  Antworten, zusätzliche Ergebnisseiten und Fremdressourcen werden abgelehnt.
- **A07:** Vollständige transitive Python-Server-Locks mit Hashprüfung, Vergleich
  der installierten Paketversionen und privatem Softwareinventar. Bisherige
  pauschale Paketstempel umgehen die Prüfung nicht mehr.

Der normale Commander-Tokenschutz bleibt optional; A03 wird nicht als allgemeine
LAN-Tokenpflicht übernommen. Die neue exklusive Benchmarksteuerung ist entsprechend
der Kienzlebench-Übergabe authentifiziert. TLS bleibt ausdrücklich zurückgestellt.
Buildprüfungen gleichen beide Commander-Codebäume ab und erlauben nur dokumentierte
Plattformunterschiede. Alle Fehlerfälle werden mit synthetischen Daten geprüft.

[Dependency-Locks und Inventare](../installer/dependency-locks/README.md) ·
[Commander-Erweiterung](commander-benchmark-api.md)
