# Prüfstand kienzledoku record 1.3.1

Stand: 27.09.2026. Lokal auf macOS; kein Commit, Push oder Deployment.

## Erfolgreich ausgeführt

- 35 Python-Tests: 33 Tests als vollständiger Lauf mit lokalen HTTP-/HTTPS-Ports,
  danach die beiden ergänzten Regressionstests zusammen mit den betroffenen
  Tests erneut. Abgedeckt: FHIR-Transaktion, Direktbetrieb, Connect-Ausfall ohne
  Fallback, exaktes Ziel, TOML/Migration/Update-Erhalt, authentifizierte lokale UI,
  CSRF/Origin/Host, unklarer Schreibausgang, Wiederherstellung und Audio-Bereinigung.
- Audio: 48-kHz-Stereo wird blockweise korrekt zu 16-kHz-Mono; erneute
  Verarbeitung eines unterbrochenen Segments verdoppelt keinen Text.
- Echter gestarteter Connect-Prozess gegen einen synthetischen lokalen
  HTTPS-Server mit eigener Test-CA: mehrfacher alter Key wird ersetzt, OAuth,
  Query, Body, Antwortstatus und Antwortinhalt bleiben erhalten; Prozess endet
  beim Schließen seiner Besitzer-Pipe.
- Go-Tests und `go vet`: Headerersetzung, Pfade, Methoden, lokale Berechtigung,
  Host/Origin, Zielprüfung und kein wiederholter Write bei Transportfehlern.
- Python-Selbsttest, Linux-Installer-Selbsttest, Shell-/Python-Syntaxprüfung
  und `git diff --check`.
- Native macOS-Fensterdatei: Universal-Binary für Intel und Apple Silicon
  neu gebaut und lokale Codesign-Verifikation erfolgreich.
- Connect: universelles macOS-Binary und Windows-x64-GUI-EXE erfolgreich gebaut.

### Nachtrag: Start der einzelnen Connect-EXE, 27.09.2026

Nach der Meldung `exit status 9009` beim direkten Öffnen der Einzel-EXE wurden
die Prüfungen vor dem Record-Start ergänzt. Fehlende Record-Dateien oder eine
fehlende gebündelte Windows-Laufzeit führen nun zu einer verständlichen Meldung.
Auf Windows wird nicht mehr automatisch `python3` aus dem PATH gestartet.

Zusätzliche Go-Regressionstests prüfen fehlende Anwendungsdateien, den
Windows-PATH-Platzhalter bei fehlender Laufzeit, explizite Interpreterpfade
sowie die weiter funktionierende Laufzeitauswahl unter macOS/Linux.
Go-Tests und `go vet` sind erfolgreich; die Windows-EXE wurde neu crosskompiliert.
Der vollständige Windows-Build bleibt wie unten angegeben auf Windows zu prüfen.

### Nachtrag: erster Windows-Buildlauf

Der vom Benutzer bereitgestellte Buildlog bestätigt unter Windows:

- Go-Tests und Connect-Build erfolgreich.
- WebView2-Fenstercontainer mit Visual Studio 18 2026 / MSVC 19.51 erfolgreich
  kompiliert und gelinkt.
- Echter Connect-HTTPS-Transporttest sowie 33 weitere Python-Tests erfolgreich.
- Abbruch ausschließlich im verbleibenden Linux-Schlüsselbundtest, weil die
  Windows-Schlüsselabfrage vor der Plattformprüfung ein Benutzerverzeichnis
  auflöste. Der Test leert absichtlich die Umgebung; unter Windows konnte
  `Path.home()` dann keinen Pfad bestimmen.

Die Plattformprüfung erfolgt jetzt vor jedem Dateizugriff. Der Fehler wurde
lokal gezielt reproduziert und der bestehende Test entsprechend verschärft.
Ein zusätzlicher Test bestätigt den weiterhin funktionierenden Windows-Zweig
mit simulierter DPAPI-Entschlüsselung. Anschließend bestanden alle 32 lokal
ausgeführten Tests ohne Testserver sowie der Record-Selbsttest. Der vollständige
Windows-Lauf mit nun 36 Python-Tests und die Setup-Erzeugung sind erneut auszuführen.

### Patchausgabe 1.3.1

Anwendungsanzeigen, Windows-Dateiversion und alle drei Installer tragen jetzt
1.3.1. Die 32 Tests ohne Testserver und der Selbsttest wurden für diesen Stand
erneut erfolgreich ausgeführt. Das universelle macOS-Fenster wurde neu gebaut
und seine Signatur geprüft; die Windows-Connect-EXE wurde neu crosskompiliert.
Die neuen ZIP-Pakete haben eigene 1.3.1-Dateinamen und einen 1.3.1-Stammordner.
Die bisherigen 1.3-Pakete bleiben separat erhalten.

## Auf Zielplattformen noch auszuführen

- Windows: kompletter Durchlauf von `windows/build.cmd` nach der Testkorrektur,
  Inno-Setup, tatsächliche Installation/Update/Deinstallation, Mikrofon,
  WebView2-Fenster im Betrieb, Taskleistensymbol und Skalierung.
- T2med und reale ASR-/Diarisierungs-/LLM-Dienste mit einem Testpatienten.
- RDP nach dem lokalen Windows-Test: Audio-Umleitung, mehrere Sitzungen,
  Trennung und Wiederaufnahme.
- macOS-/Linux-Installer im tatsächlichen Benutzerprofil sowie Linux unter
  X11 und Wayland. Bestehende lokale Installationen wurden nicht überschrieben.
- Sichtprüfung der vollständigen Oberfläche: Die automatische Dateivorschau
  wurde von der Browserrichtlinie abgelehnt. SVG und daraus erzeugtes Icon
  wurden separat geprüft; HTML-Verträge sind durch Tests geprüft.

Die Windows-Buildumgebung ist auf diesem Mac nicht vorhanden. Die bereitgestellte
Windows-ZIP-Datei ist daher ausdrücklich ein **Build-Paket**, kein bereits fertig
gebautes und unter Windows abgenommenes Record-Setup. Connect und der native
Fenstercontainer wurden auf dem Windows-Rechner bereits erfolgreich gebaut;
der vollständige Test-/Setup-Durchlauf steht noch aus. Die Anleitung steht in
[windows/README.md](../windows/README.md).

Der zusätzliche Sol-Worker konnte nicht starten, weil sein konfigurierter
Codex-CLI-Pfad fehlte. Umsetzung und Review wurden im Hauptprozess vorgenommen;
es wurde kein anderer Account oder Ersatzworker verwendet.
