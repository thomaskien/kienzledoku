# Prüfstand kienzledoku record 1.3.2

Stand: 27.09.2026. Korrektur der beim ersten Windows-Start gemeldeten Fehler.
Kein Commit, Push oder Deployment.

## Reproduzierte Fehler und Korrekturen

- Die tatsächliche Einstellungsseite brach mit `ValueError: unsupported format
  character ';'` ab. Ein nicht maskiertes `width:100%` in einer Python-Vorlage
  mit Prozentformatierung verursachte eine leere HTTP-Antwort. Der neue
  HTTP-Integrationstest zeigte vor der Korrektur `RemoteDisconnected`.
- Die bisherige 303-Weiterleitung konnte in Chromium nach einem externen
  Einstieg HTTP 403 auslösen: Das neue `SameSite=Strict`-Cookie wurde in diesem
  Navigationskontext nicht mitgeschickt. Im Browser mit einem synthetischen
  externen Einstieg reproduziert. Jetzt wird zunächst ein lokales Dokument
  geladen, das anschließend per `location.replace` zur Oberfläche navigiert.
  Cookie bleibt `HttpOnly; SameSite=Strict`; das Token steht nicht im HTML.
  Die Zwischenseite hat eine CSP mit Skript-Nonce und erlaubt keine Frames.
- Beim anschließenden echten Browser-Test zeigte das Speichern noch HTTP 403:
  `Referrer-Policy: no-referrer` verursachte bei Formular-POSTs `Origin: null`.
  Die Einstellungsseite verwendet jetzt `same-origin`. Fremde und null-Origins
  werden weiterhin abgelehnt, CSRF-Prüfung bleibt unverändert aktiv.

## Erfolgreiche Prüfung

- Vollständige Python-Suite: 37 Tests, einschließlich echtem Connect-Prozess
  gegen synthetischen HTTPS-Server sowie HTTP-Tests für Record und Einstellungen.
  Nach der letzten Richtlinienkorrektur die vier betroffenen HTTP-Tests erneut.
- Echter Chrome-Test mit Playwright und isolierten temporären Benutzerprofilen:
  jeweils aus leerem Fenster und externem Navigationskontext. Oberfläche,
  Sitzungscookie, Logo, Neuladen, Einstellungsänderung, Speichern und Schließen
  erfolgreich; Server beendet sich nach Schließen. Keine Patienten- oder
  bestehenden Benutzereinstellungen verwendet.
- Record-Selbsttest und Linux-Installer-Selbsttest mit Version 1.3.2.
- Universelles macOS-Fenster für Intel/Apple Silicon neu gebaut und seine lokale
  Codesign-Signatur geprüft. Windows-x64-Connect erneut crosskompiliert.
- Shellsyntax und `git diff --check` erfolgreich. ZIP-Inhalte und Prüfsummen
  werden vor Bereitstellung geprüft; ältere Pakete bleiben unverändert erhalten.

Der Browser-Test liegt unter `tests/ui_startup_smoke.cjs`. Er ist optional und
setzt Node.js, Playwright sowie Chrome oder Edge voraus. Beispiel bei vorhandenen
Testwerkzeugen: `node tests/ui_startup_smoke.cjs /pfad/zu/python chrome`.
Der reguläre Windows-Build benötigt diese zusätzlichen Browser-Testwerkzeuge nicht.

## Noch auf dem Windows-Rechner zu prüfen

Der neue Windows-Setup-Build und der tatsächliche Start in WebView2 müssen auf
Windows wiederholt werden. Chrome auf macOS ersetzt diese Plattformabnahme nicht.
Das Build-Paket enthält die Quellen; `windows\build.cmd` erzeugt nach allen Tests
`build\windows\kienzledoku-record-1.3.2-windows-x64-setup.exe`.
Vor dem Installieren alte Record-Fenster beenden. Bestehende Konfiguration bleibt
bei einem Update erhalten. Mikrofon, T2med, KI-Dienste und RDP bleiben Teil der
anschließenden lokalen Abnahme.

Die gemeinsamen Python-Korrekturen gelten für Windows, macOS und Linux. Der
Sol-Worker konnte weiterhin nicht verwendet werden, weil sein konfigurierter
Codex-CLI-Pfad fehlt. Untersuchung, Korrektur und Review erfolgten im Hauptprozess.
