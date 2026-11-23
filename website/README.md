# Quellen der Homepage

Diese Quellen aktualisieren die Startseite von [kienzledoku.de](https://kienzledoku.de/).
Die vollständige bestehende Website mit Benchmark-Rohdaten bleibt die Basis.
`build.py` übernimmt sie, ergänzt nur die Startseiten-Dateien und prüft, dass
Grafikkartentabellen, Filter, Benchmarkseiten und gemeinsame Skripte unverändert bleiben.
Auf der Grafikkartenseite wird nur der veraltete Hinweis auf Version 1.3.1 ersetzt.

```bash
python3 website/build.py --baseline /pfad/zum/bisherigen/dist --output /pfad/zum/neuen/dist
python3 website/check.py /pfad/zum/neuen/dist
python3 -m http.server 8768 --bind 127.0.0.1 --directory /pfad/zum/neuen/dist
```

Aufmacher und Pegelscreenshot werden aus `docs/images/` übernommen, ebenso die
Gesprächsgrafik. Dadurch zeigen Homepage und GitHub dieselben Bilder. Die
Startseite erhält ein eigenes Stylesheet, das andere Seiten nicht verändert.
YouTube-Player werden weiterhin erst beim Anklicken geladen.

Die drei neuen Videovorschaubilder stammen von den zugehörigen öffentlichen
YouTube-Videos des Projektbetreibers. Die Aufnahme-Screenshots hat der Betreiber
für diese Verwendung bereitgestellt; sie werden ohne Bildbearbeitung übernommen.

## Downloadstand

Die Downloadkarten für Version 1.8.3 verweisen direkt auf den Windows-Installer, das Linux-Archiv und beide macOS-DMGs. Die Mac-Anleitung erklärt die Auswahl zwischen dem Universal-Client und dem Paket mit lokalem Commander.

`bootstrap/install_linux.sh` wird als `/install_linux.sh` veröffentlicht. Es liest
öffentliche stabile Releases, wählt das neueste Linux-Paket nach Versionsnummer,
prüft Downloadziel, Größe, SHA-256 und Archivpfade und startet erst danach den
enthaltenen Installer. Ohne vollständiges Release gibt es keine Installation.

Das Skript im Repository-Wurzelverzeichnis gehört zum älteren Quellcode und wird
von dieser Dokumentationsänderung nicht ersetzt. Bestehende Installationspakete
werden nicht nachträglich verändert.

## Veröffentlichung

Nur statische Website-Dateien an den bestehenden Webroot ausliefern. Vorher den
aktuellen Live-Stand vollständig mit der Basis vergleichen, während der
Vorbereitung entstandene Fremdänderungen erhalten, eine Sicherung anlegen und
den geprüften Stand atomar austauschen. Apache-Konfiguration, Zertifikate und
andere Projekte auf dem gemeinsamen Host bleiben unverändert.
