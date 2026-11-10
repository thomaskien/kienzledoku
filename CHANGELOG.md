# Änderungsprotokoll

## Commander-Integration – 2026-11-10

- Record 1.3.3 und Connect mit der bestehenden Commander-Anbindung zusammengeführt:
  gemeinsame KI-Adresse, serverseitiger Modellkatalog und Verarbeitung nach
  tatsächlichem Aufnahmeende und Abschluss der ASR-Blöcke.
- Linux-Commander aus der Übergabe übernommen; seine installierten Quellen auf
  dem bisherigen Server wurden vor der Integration per SHA-256 abgeglichen.
- Windows-Server-Installer 1.12 einschließlich Quellen und fertiger Pakete
  unverändert unter `server-windows/` übernommen. Der Benutzer bestätigt den
  erfolgreichen Windows-Betrieb; historische Prüfberichte bleiben unverändert.
- Neue Client-Konfigurationen verwenden Commander; bestehende Konfigurationen
  und ihre ausdrücklich gewählte FHIR-Anbindung bleiben erhalten.
- Keine Modelländerung, kein neuer Hersteller-Key und kein Server-Deployment.


## Record 1.3.3 – 2026-09-27

- UTF-8-Ausgabe im Aufnahmeprozess ausdrücklich gesetzt, auch für die isolierte
  Windows-Python-Laufzeit, die Umgebungsvariablen ignoriert. Live-Umlaute und
  Gerätenamen werden unverändert an die Oberfläche übertragen.
- Neue Aufnahmen beginnen beim Öffnen; die T2med-Patientenabfrage läuft parallel
  und blockiert die Aufnahmebedienung nicht. Patientendaten erscheinen ohne
  Seitenneuladen. Wiederherstellung und manuell gestoppte Aufnahmen starten
  nicht erneut automatisch. Ohne geladenen Patienten bleibt Schreiben gesperrt.
- Windows-Setup fragt T2med-, ASR-, Sprechertrennungs- und LLM-Adressen samt
  Betriebsart/Zertifikatsoptionen ab und wartet auf Speichern. Bestehende Werte
  werden vorbelegt; Mikrofon, Ausgabeformat und eigene Keys bleiben erhalten.
- Vollständig bestätigter FHIR-Transaktionsrollback wird als „Nicht gespeichert“
  angezeigt und erzeugt keine widersprüchliche Unklarheitswarnung. Entwurf bleibt
  erhalten. Fehlende/unvollständige Antworten sperren weiterhin Wiederholungen;
  es gibt keinen automatischen Schreibversuch.
- Plattformversionen und Installer auf 1.3.3 aktualisiert. Gemeinsame Korrekturen
  gelten für Windows, macOS und Linux. Neue Prozess-, HTTP- und Browserprüfungen.

## Record 1.3.2 – 2026-09-27

- Einstellungsseite: Prozentzeichen in der CSS-Vorlage korrekt maskiert. Die
  Seite wird wieder vollständig ausgeliefert; der durch den Formatierungsfehler
  verursachte Abbruch mit `ERR_EMPTY_RESPONSE` entfällt.
- Lokaler UI-Start: Eine kurze lokale HTML-Seite setzt das Sitzungscookie und
  öffnet anschließend die Oberfläche. Die bisherige HTTP-Weiterleitung konnte
  in Chromium bei einem externen Navigationskontext zu HTTP 403 führen.
  `HttpOnly`, `SameSite=Strict`, Host-/Origin-Prüfung und CSRF bleiben aktiv.
- Einstellungsformular verwendet `Referrer-Policy: same-origin`, damit Chromium
  bei lokalen Formular-POSTs den korrekten Origin sendet. Die bisherige Richtlinie
  führte zu `Origin: null` und damit ebenfalls HTTP 403 beim Speichern.
- Neuer HTTP-Regressionstest für das tatsächliche Öffnen, Speichern und
  Schließen der Einstellungen; optionaler echter Browser-Test für den Start aus
  einem leeren Fenster und aus einem externen Navigationskontext.
- Alle drei Plattform-Installer und Versionsanzeigen auf 1.3.2 angehoben.

## Record 1.3.1 – 2026-09-27

- Windows-Schlüsselabfrage prüft die Plattform vor jedem Profilzugriff; der
  unter Windows fehlschlagende Linux-Schlüsselbundtest bleibt aktiv und besteht.
- Connect meldet fehlende Record-Dateien und Laufzeit verständlich und verwendet
  unter Windows keinen automatischen `python3`-PATH-Fallback mehr (Fehler 9009).
- Versionsanzeigen, native Fenster, macOS-/Linux-Installer, Windows-Setup und
  Auslieferungsdateien tragen 1.3.1. Die bisherigen 1.3-Pakete bleiben separat.
- Windows-Log bestätigt den nativen Build und 34 der damaligen 35 Python-Tests;
  die korrigierten Tests sind lokal geprüft. Vollständiger Windows-Durchlauf
  einschließlich Setup steht noch aus.

## 1.3 – kienzledoku record, Windows und Connect (in Vorbereitung)

Die Versionsnummer 1.3 ist der ausdrücklich gewählte neue Produktstand nach
1.3.1. Neuer Name und vorhandenes Record-Logo auf allen Plattformen.

- Schlanker Go-Connect-Starter und authentifizierter HTTPS-Proxy, der sämtliche
  eingehenden API-Keys ersetzt und FHIR/OAuth sowie Antworten durchreicht.
- Expliziter Direktbetrieb bleibt unabhängig von Connect; zunächst Demo-Key.
- Windows-WebView2-Fenster, gebündelte Python-Laufzeit und Build/Setup-Skripte.
- macOS-/Linux-Installer für denselben Stand, TOML und grafische Einstellungen.
- Native Mikrofonformate, stabile Gerätekennung, PCM-Konvertierung und Test.
- Sitzungsweise Wiederherstellung und Sperre nach unklarem Schreibausgang.
- Prüfung auf dem Mac; Windows-/RDP-Abnahme noch auszuführen.

Alle wesentlichen Änderungen an Kienzledoku werden in diesem Dokument
festgehalten. Das Format orientiert sich an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unveröffentlicht]

- Noch keine Änderungen.

## [1.3.1] – 2026-08-26

### Behoben

- Der WebKitGTK-Fensterprozess erhält unter Ubuntu 24.04 über ein gezieltes
  AppArmor-Profil die für seine Bubblewrap-Sandbox erforderliche
  User-Namespace-Berechtigung. Die systemweite Schutzfunktion bleibt aktiv.
- Das profilierte Fensterprogramm wird root-eigen unter `/usr/local/libexec`
  installiert und kann daher nicht durch einen unprivilegierten Benutzer
  ersetzt werden.
- Native GTK-/WebKit-Fehler und der Exit-Code des Fensterprozesses landen nun
  im geschützten Diagnoseprotokoll.

### Dokumentation

- Installationsanleitung klar in Clientwahl (macOS oder Ubuntu) und davon
  unabhängige KI-Serverwahl (Apple Silicon oder Ubuntu/NVIDIA) gegliedert.

## [1.3.0] – 2026-08-26

### Hinzugefügt

- Schlanker Client für Ubuntu 24.04 LTS auf x86_64.
- Desktopunabhängiger GTK-4-/WebKitGTK-6.0-Fenstercontainer für X11 und
  Wayland.
- Einsehbarer `install_linux.sh` mit XDG-URL-Handler, Ubuntu-Abhängigkeiten,
  Client-venv, Selbsttest und Dienstprüfung.
- Direkte GitHub-Installation per `curl | bash`; der Installer lädt dafür den
  vollständigen Quellbaum als temporäres Archiv.
- Speicherung eigener T2med-API-Schlüssel über Linux Secret Service.
- Linux-Deinstallation und Rückkehr zum öffentlichen Demo-Key.

### Sicherheit

- OAuth-haltige Linux-Deep-Links werden über eine anonyme Pipe an den
  langlebigen Python-Prozess übergeben und nicht auf den Datenträger geschrieben.
- Unter Linux ist pro Benutzer nur eine aktive Dokumentationssitzung erlaubt.
- Das WebKitGTK-Fenster verwendet eine nichtpersistente Netzwerksitzung und
  erlaubt interne Navigation nur zum zufällig gewählten Loopback-Port der
  aktuellen Sitzung.

## [1.2.1] – 2026-08-26

### Behoben

- Der Mac-Installer fragt den T2med-FHIR-Host ab und speichert ihn als lokale
  Freigabe. Die in 1.2 irrtümlich fest codierte Test-IP `10.0.83.120` ist nur
  noch der änderbare Vorschlagswert.

### Dokumentation

- T2med-Einrichtung um den abschließenden Menüleistenknopf ergänzt.
- Host-Firewall auf dem KI-Server als optionale zusätzliche Absicherung im
  geschützten Praxisnetz klargestellt.
- Nicht umgesetzten Zertifikats-Hinweis entfernt.
- Datenschutz-Selbsteinschätzung des Betreibers für den ausschließlich
  praxisinternen Betrieb ergänzt.

## [1.2] – 2026-08-25

### Hinzugefügt

- Eigenes natives, bildschirmangepasstes WebKit-Fenster ohne Browserleiste.
- Live-Transkript während der Mikrofonaufnahme.
- Getrennte Statusanzeige für T2med, ASR, Diarisierung und LLM.
- Editierbares Sprechertranskript mit erneuter LLM-Zusammenfassung ohne neue
  Aufnahme oder Spracherkennung.
- Fortsetzen der Aufnahme unter Erhalt und erneuter Zusammenfassung des
  vollständigen Gesprächsverlaufs.
- Wahl zwischen vier strukturierten T2med-Einträgen und einem gemeinsamen
  Freitext-Eintrag mit konfigurierbarem Kürzel.
- Autoritative Installer-Konfiguration für getrennte ASR-, Diarisierungs- und
  LLM-Ziele.
- Universal-Binary des nativen Fensters für Intel und Apple Silicon.
- Netzwerkfreier Selbsttest und automatisierte Unit-Tests.
- Optionaler, komponentenweise installierbarer Local-AI-Installer für
  Qwen/llama.cpp auf Metal, Whisper large-v3 auf MLX und pyannote auf MPS.
- Gemeinsamer macOS-Installer, der lokale KI-Dienste und Kienzledoku-App
  nacheinander einrichtet.
- Explizite additive Installer für LLM-, ASR- und Diarisierungsserver.
- Ubuntu/NVIDIA-Serverpaket mit Hostvorbereitung, rollenbezogenen Installern,
  pyannote, status-/test-Aktionen und streng geprüftem Final-Block-ASR-Patch.
- Versionsunabhängige Repository-Struktur ohne Release-Unterverzeichnis.

### Geändert

- Produktname, Installationspfade, Schlüsselbund-Dienst und kanonisches
  URL-Schema verwenden Kienzledoku; frühere WhisperDoku-Bezeichnungen bleiben
  nur für Herkunft und Kompatibilität erhalten.
- Dokumentationsübernahme erfolgt als atomare FHIR-Transaktion.
- Temporäre Audio-, Transkript- und LLM-Dateien werden geschützt verarbeitet
  und nach Abschluss entfernt.
- Die Grenze des öffentlichen T2med-Demo-Keys von 100 einzelnen FHIR-Requests
  pro APS-Serverprozess sowie der danach erforderliche Neustart des
  T2med-/APS-Serverprozesses werden prominent ausgewiesen.

### Sicherheit

- FHIR-Ziele sind auf Loopback und den explizit bestätigten T2med-Testserver
  begrenzt.
- Tokens, API-Schlüssel und Dokumentationsinhalte werden nicht protokolliert.
- Eigene T2med-API-Schlüssel werden im macOS-Schlüsselbund gespeichert.
- Local-AI-Dienste verwenden standardmäßig ausschließlich Loopback; eine
  ungeschützte LAN-Bindung erfordert eine ausdrückliche Bestätigung.

Die technischen Referenzstände und ihre Prüfsummen stehen in
[`PROVENANCE.md`](PROVENANCE.md).
