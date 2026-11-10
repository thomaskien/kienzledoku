# Prüfstand kienzledoku record 1.3.3

Stand: 27.09.2026. Lokale Quellen und Build-Pakete; kein Commit, Push oder
Deployment. Windows 1.3.2 wurde vom Benutzer im Direktbetrieb getestet.

## Änderungen

- Umlaute während der Aufzeichnung: Der Aufnahmeprozess schreibt stdout und
  stderr ausdrücklich als UTF-8. Das funktioniert auch mit dem isolierten
  Windows-Embedded-Python, das `PYTHONIOENCODING` ignoriert. Ein echter Kindprozess
  wird im Regressionstest zunächst auf cp1252 gesetzt; anschließend müssen
  Live-Transkript, Gerätename und Sprechertext einschließlich Ä/Ö/Ü/ß und α
  unverändert beim Record-Manager ankommen. Der Test verwendet kein Mikrofon.
- Eine neue Aufnahme beginnt beim Öffnen, unabhängig von der Dauer der
  T2med-Patientenabfrage. Die Abfrage läuft ohne die UI-Sperre im Hintergrund.
  Name und Geburtsdatum erscheinen ohne Neuladen der Seite. Schreiben bleibt
  ohne geladenen Patienten gesperrt. Wiederherstellung startet keine Aufnahme;
  erneutes Laden der Patientendaten setzt keine gestoppte Aufnahme fort.
- Windows-Installer öffnet einen verpflichtenden Serverdialog und wartet auf
  „Speichern und Installation abschließen“. T2med, ASR, Sprechertrennung, LLM,
  Betriebsart und Zertifikatsoptionen sind mit vorhandenen Werten vorbelegt.
  Nicht angezeigte Aufnahmeoptionen und eigene Keys bleiben erhalten. Abbrechen
  verändert die bestehende Konfiguration nicht. `-NoOpen`/Inno-Silent überspringt
  den Dialog für ausdrücklich unbeaufsichtigte Installationen.
- Eine vollständige Transaktionsantwort mit error/fatal-OperationOutcome wird
  als bestätigter Rollback behandelt, gemäß Abschnitt 5.4 des
  [T2med-Integrationsleitfadens](https://github.com/T2med/fhir-demoapplication/blob/main/Integrationsleitfaden-FHIR-API.md).
  Der Entwurf bleibt erhalten, die widersprüchliche Unklarheitswarnung entfällt.
  Fehlende, unvollständige oder nicht eindeutig bestätigte Antworten bleiben
  unklar und sperren die Wiederholung. Es erfolgt nie ein automatischer Retry.
- Alle Versionsanzeigen, Windows-, macOS- und Linux-Installer tragen 1.3.3.

## Erfolgreiche lokale Prüfungen

- 44 Python-Tests: `python -m unittest discover -s tests -v` mit Python 3.14.6.
  Darunter echter Connect-Prozess gegen einen synthetischen HTTPS-Server:
  Austausch eingehender API-Keys, Erhalt von OAuth, Nutzdaten und Antwortstatus.
  Außerdem Live-Unicode, verzögerte/fehlgeschlagene Patientenabfrage,
  Wiederherstellung, Schreibsperren, bestätigter Rollback und Setup-Konfiguration.
- Echter Chrome-Test: Einstellungen aus leerem und externem Navigationskontext
  sowie Serverdialog während der Installation. Logo, Cookie, Formular-POST,
  Speichern und Prozessende geprüft. Temporäre Einstellungen ausschließlich.
- Echter Chrome-Test des Record-Sitzungsablaufs: automatische synthetische
  Aufnahme vor Freigabe der Patientenantwort, Live-Umlaute, nachgeladene
  synthetische Patientendaten ohne Reload, Stoppen, Patient neu laden und
  Schließen. Mikrofon, KI-Dienste und T2med sind in dieser Prüfung simuliert.
- Record-Selbsttest, Linux-Installer-Selbsttest, Shellsyntax, Python-3.9-Syntax
  und `git diff --check`.
- macOS-Fenster für Intel/Apple Silicon neu gebaut; lokale Ad-hoc-Signatur
  verifiziert. Connect für Windows x64 crosskompiliert.
- ZIP-Inhalte werden byteweise mit den Quellen verglichen und ihre CRC geprüft.
  SHA-256-Prüfsummen aller Versionen werden geprüft; alte Pakete bleiben erhalten.

Optionale Browserprüfungen bei installiertem Node.js, Playwright und Chrome/Edge:

```text
node tests/ui_startup_smoke.cjs /pfad/zu/python chrome
node tests/ui_record_smoke.cjs /pfad/zu/python chrome
```

Der Windows-Build benötigt diese optionalen Browserwerkzeuge nicht. Er führt die
Python-Suite in seiner gebündelten CPython-3.12-Laufzeit und die Go-Tests aus.
Der konfigurierte Sol-Worker ist weiterhin nicht verfügbar: Sein festgelegter
Codex-CLI-Pfad fehlt. Implementierung und abschließendes Review erfolgten im
Hauptprozess; kein anderer Account oder Worker wurde verwendet.

## Windows-Abnahme

Das Build-Paket entpacken bzw. den bisherigen Quellordner aktualisieren und
`windows\build.cmd` ausführen. Bereits installierte Entwicklungswerkzeuge und
der bisherige `build`-Ordner können weiterverwendet werden. Der Installer liegt
danach unter `build\windows\kienzledoku-record-1.3.3-windows-x64-setup.exe`.
Das einzelne Connect-Binary ist kein Installer; das vollständige Setup enthält
Connect und Record samt Laufzeit.

Noch auf Windows zu prüfen: nativer Build/Setup, Serverdialog, echte
Mikrofonaufnahme mit Live-Umlauten und sofortigem Start, Connect mit dem eigenen
T2med-System sowie RDP. Die lokalen Tests ersetzen diese Plattformabnahme nicht.
Für Connect ausdrücklich „Über Connect“ wählen und in T2med die URL
`kienzledoku://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}`
verwenden. Der bisherige Direktbetrieb belegt keinen praktischen Connect-Test.
