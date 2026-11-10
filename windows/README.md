# kienzledoku record 1.3.3 für Windows

Der Windows-Client verwendet das vorhandene Record-Frontend in einem eigenen
WebView2-Fenster. Mikrofonaufnahme läuft über PortAudio/WASAPI; ASR,
Sprechertrennung und LLM werden über den Commander angesprochen. Er kann auf
demselben Windows-Rechner in der eigenen WSL2-Umgebung oder auf einem separaten
Server laufen. Der fertige [Windows-Server-Installer 1.12](../server-windows/README.md)
bleibt von diesem Client-Build unabhängig.
Das SVG aus `assets/kienzledoku-record.svg` liefert auch das Taskleistensymbol.

**Neu in 1.3.3:** Live-Transkript und Gerätenamen werden auch mit der gebündelten
Windows-Python-Laufzeit durchgängig in UTF-8 übertragen. Eine neue Aufnahme
beginnt beim Öffnen; das Laden der Patientendaten erfolgt parallel. Offene
Wiederherstellungen starten weiterhin erst nach ausdrücklicher Fortsetzung.
Der Installer wartet auf einen eigenen Schritt zur Servereinrichtung.
Die Startkorrekturen aus 1.3.2 (`ERR_EMPTY_RESPONSE` und HTTP 403) sind enthalten.

**Die einzelne `kienzleconnect-1.3.3-windows-x64.exe` ist kein Installer und startet
allein noch keine Anwendung.** Sie benötigt die Record-Dateien und die eigene
Python-Laufzeit aus dem vollständigen Paket. Nach Installation der
Entwicklungswerkzeuge wird deshalb `windows\build.cmd` aus dem entpackten
Build-Paket ausgeführt. Erst danach das erzeugte Record-Setup starten.

Frühere Connect-Builds meldeten beim Doppelklick auf die einzelne EXE unter
Umständen nur `exit status 9009`: Der fehlende Laufzeitpfad führte zu einem
Aufruf von `python3`, der unter Windows ein Store-Platzhalter sein kann.
Connect prüft nun vor dem Start, ob Record und die gebündelte Laufzeit vorhanden
sind, und zeigt andernfalls die notwendige Abhilfe an. Ein automatischer
Windows-PATH-Fallback findet nicht mehr statt.

## Build auf dem Windows-Testrechner

Voraussetzungen: Windows x64, **CPython 3.12 x64**, Go >= 1.20,
CMake >= 3.20, Visual Studio 2022 Build Tools mit **Desktopentwicklung mit C++**
(MSVC und Windows SDK) sowie Inno Setup 6 für die Setup-Datei.
Python, Go und CMake müssen im PATH stehen; alternativ findet das Skript Python
über `py -3.12`. Der Testrechner benötigt Internet für die Build-Abhängigkeiten.

Die offiziellen Installationsquellen sind
[Python 3.12.10](https://www.python.org/downloads/release/python-31210/),
[Go](https://go.dev/dl/), [CMake](https://cmake.org/download/),
[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
und [Inno Setup](https://jrsoftware.org/isdl.php).

Das Build-Paket vollständig entpacken. Anschließend **`windows\build.cmd`**
doppelklicken. Das Skript baut Connect und den Fenstercontainer, bündelt eine
eigene Python-Laufzeit, installiert die festgelegten Client-Abhängigkeiten und
führt die Python-/Go-Tests aus. Es schreibt erst danach die Auslieferungsdateien:

```text
build\windows\kienzledoku-record-1.3.3-windows-x64.zip
build\windows\kienzledoku-record-1.3.3-windows-x64-setup.exe
```

Ohne Inno Setup lässt sich zunächst nur das ZIP bauen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1 -SkipInstaller
```

CPython 3.12 ist absichtlich festgelegt: Der Build benötigt das passende
offizielle embeddable-Paket. WebView2-SDK: `1.0.3537.50`. Die Build-Tools werden
nicht auf späteren Zielrechnern benötigt. Die EXE-Dateien sind derzeit nicht mit
einem Herausgeberzertifikat signiert; eine Windows-Reputationswarnung ist möglich.

## Installation und lokaler Ersttest

1. Setup starten; alternativ das fertige ZIP entpacken und `install.cmd` öffnen.
   Die Installation erfolgt ohne Administratorrechte für den aktuellen Benutzer.
2. Microsoft **Edge WebView2 Evergreen Runtime x64** muss vorhanden sein.
   Fehlt sie, nennt die Installation die Abhilfe. Der signierte Offline-Installer
   `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` kann neben `install.ps1` liegen.
   Siehe [Microsofts Verteilungsanleitung](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
3. Während der Installation öffnet sich **„Server für die Installation einrichten“**.
   Dort die **genaue** T2med-FHIR-Basis und die Commander-Verbindung eintragen.
   Für bestehende Installationen bleiben die bisherigen einzelnen KI-Adressen erhalten.
   Bei einem Update stehen hier die bisherigen Werte. Für ein selbst signiertes T2med-Zertifikat bevorzugt die CA-Datei
   wählen; die ausdrücklich anwählbare Zertifikatsausnahme gilt nur für dieses Ziel.
4. Zunächst „Über Connect“ wählen. Ein eigener Key ist nicht nötig: Dieser Build
   enthält den öffentlichen Demo-Key. Ein mitgesendeter alter Key wird ersetzt.
   Mit **„Speichern und Installation abschließen“** bestätigen. Das Setup wartet
   auf diesen Schritt. Bei Abbrechen bleibt die bisherige Konfiguration erhalten;
   zum Abschließen das Setup erneut starten.
5. Bei Bedarf „kienzledoku record“ im Startmenü öffnen. In den Einstellungen
   „Mikrofone anzeigen“ wählen, das Gerät auswählen, den 3-Sekunden-Test ausführen,
   anschließend speichern. Beim Test wird kein Audio gespeichert oder versendet.
6. In T2med folgende Drittanbieter-URL eintragen:

   ```text
   kienzledoku://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}
   ```

7. Mit einem Testpatienten öffnen: Die Aufnahme startet automatisch, während
   der Patientenname geladen wird. Name prüfen, sprechen, stoppen und den Entwurf
   kontrollieren. Die Übernahme bleibt bis zum Laden des Patienten gesperrt. Erst „In T2med übernehmen“ schreibt die Dokumentation.

Für unabhängigen **Direktbetrieb** in den Einstellungen „Direktbetrieb“ wählen
und folgende URL in T2med verwenden:

```text
kienzledoku-record://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}
```

Dabei ist weder ein laufendes noch ein installiertes Connect erforderlich.
Ein eigener Direkt-Key kann grafisch gespeichert werden (Windows DPAPI).
Ohne eigenen Key gilt der Demo-Key. Die in TOML gewählte Betriebsart ist
maßgeblich; bei Ausfall von Connect gibt es keinen automatischen Direktzugriff.

## Updates, Konfiguration und offene Arbeit

- Programm: `%LOCALAPPDATA%\Programs\kienzledoku record`
- Einstellungen: `%LOCALAPPDATA%\kienzledoku record\config.toml`
- Wiederherstellung: darunter `sessions\windows-<Anmeldesitzungsnummer>`
- Diagnose: darunter `record.log`

Updates belegen den Serverdialog mit den bisherigen Werten vor. Erst ausdrücklich
gespeicherte Serveränderungen werden übernommen; Mikrofon, Ausgabeformat und
gespeicherte Direkt-Keys bleiben erhalten. `install.ps1 -Config C:\Pfad\config.toml`
belegt nur eine neue Installation vor. Für vorbereitete unbeaufsichtigte
Installationen überspringt `-NoOpen` den Dialog; ebenso ein Inno-Silent-Setup. Auch bei
der Deinstallation bleiben Einstellungen und offene Arbeit erhalten.

„Sichern und schließen“ bewahrt Entwurf, Transkript und gegebenenfalls
unterbrochenes Audio lokal auf. Beim erneuten T2med-Aufruf desselben Kontextes
wird die Wiederherstellung angeboten. Audio wird erst nach ausdrücklicher
Fortsetzung erneut verarbeitet. Nach erfolgreicher Übernahme oder bewusstem
Verwerfen werden die Wiederherstellungsdaten und Audio-Zwischendateien gelöscht.
Diese Daten sind über das Benutzerprofil geschützt, nicht zusätzlich verschlüsselt.

Wenn eine vollständige T2med-Transaktionsantwort ausdrücklich den gesamten
Vorgang zurückrollt, bleibt der Entwurf erhalten und kann nach Behebung der
Ursache mit einem neuen Klick übertragen werden. Es erfolgt keine automatische
Wiederholung. Ein unklarer Schreibausgang blockiert eine zweite Übertragung. Zuerst in T2med
prüfen, ob die Dokumentation angekommen ist. Nur wenn sie **nicht** übernommen
wurde, die entsprechende Freigabe in Record betätigen. Kein automatischer Retry.

## Prüfliste für den Windows-Rechner

- Build, Installation, Taskleistensymbol und Verhalten bei 100/150/200 % Skalierung.
- Lokales Mikrofon, Gerätewechsel, Abziehen des Mikrofons, Minimieren und Alt-Tab.
- Direkt- und Connect-Betrieb mit unverändertem FHIR-Kontext/OAuth.
- Derselbe Kontext erneut: vorhandenes Fenster aktivieren; anderer Kontext:
  laufenden Vorgang nicht überschreiben.
- Sichern, erneutes Öffnen/Wiederherstellen, ausdrückliches Verwerfen.
- Erfolgreiche Übernahme schließt das Fenster; Netzwerkabbruch beim Schreiben
  löst keinen zweiten Schreibversuch aus.
- Update erhält Einstellungen; Deinstallation entfernt eigene URL-Handler.

RDP danach separat testen: Aufnahmeumleitung im RDP-Client und auf dem Server
freigeben (`audiocapturemode:i:1`), mehrere Anmeldesitzungen, Trennen/Wiederverbinden
und bewusste Wiederaufnahme prüfen. Auf dem Mac wurden gemeinsame Logik,
Audio-Konvertierung und die echte Connect-HTTPS-Verbindung getestet und Connect
für Windows crosskompiliert. Der erste Windows-Buildlog bestätigt inzwischen
den erfolgreichen MSVC-Build des nativen Fensters und den Connect-HTTPS-Test.
Die Version 1.3.2 wurde inzwischen vom Benutzer im Windows-Direktbetrieb getestet.
**Für 1.3.3 sind der neue Setup-Durchlauf mit Serverdialog, Live-Umlaute,
automatischer Aufnahmestart sowie Connect mit T2med noch praktisch auf Windows
zu prüfen.** Echte Windows-Mikrofone, Taskleiste und RDP können die lokalen
macOS-/Browser-Tests nicht vollständig abnehmen.

Bei diesem Update die Dateien im **bisherigen Quellordner** ersetzen und
`windows\build.cmd` erneut starten. Die bereits installierten Entwicklungswerkzeuge
und der vorhandene `build`-Ordner können weiterverwendet werden.
