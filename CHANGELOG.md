# Änderungsprotokoll

## 1.7.6 — 15.11.2026

- Connect ist bei neuen Clientinstallationen auf macOS, Linux und Windows
  einheitlich voreingestellt. Updates übernehmen vorhandene Einstellungen;
  auch ältere Konfigurationen mit impliziter Direktverbindung bleiben direkt.
- MIT-Lizenz unverändert in allen Installationspaketen und installierten
  Programmverzeichnissen mitliefern. Keine weiteren Funktions- oder UI-Änderungen.

## 1.7.5 — 15.11.2026

- Windows: kompakte Dienststatusanzeigen im Mac-/Linux-Stil statt gleich breiter
  Rasterfelder. Bei Platzmangel zuerst Version und Autorenname ausblenden;
  verbleibende Texte bei Bedarf mit vollständigem Tooltip kürzen. Kein Umbruch
  der Statuszeile. Mac-/Linux-Darstellung bleibt erhalten.
- Aufnahme-Einstellungen: Stilleschwellen-Regler direkt im laufenden Pegelbalken.
  Gemeinsame dBFS-Skala, vollständig transparente Reglerbahn und transparenter
  Griff mit Umriss, damit der Pegelausschlag sichtbar bleibt.
- Audio: zusätzliche adaptive Pegelschwelle entfernt. Blockbildung auch ohne
  vorher erkannte Sprache spätestens nach 20 Sekunden; VAD überspringt weiterhin
  reine Stille. Vor-/Nachlauf, Zeitachse und Client-Einstellungen bleiben erhalten.
- Mac: Startfehler beim Abruf der Commander-Einstellungen sichtbar erklären,
  einschließlich abgelehntem Token. Keine automatische Wiederholung von Aufträgen.
- Gemeinsamer Versionsstand für Mac, Linux und Windows; aktive Versionsanzeigen
  in Einstellungen, nativen Fenstern und Installer angeglichen.

## 1.7.4 — 14.11.2026

- Windows: fehlende Microsoft-C++-x64-Laufzeit für ONNX/VAD automatisch von
  Microsoft beziehen, Signatur prüfen und mit sichtbarem Status installieren.
- VAD vor der Serverinstallation und vor dem Clientaustausch prüfen;
  ursprüngliche Fehlerausgabe und erforderliche Neustarts verständlich anzeigen.
- Fehlende Windows-Abhängigkeit `pyreadline3` ergänzen. Der Cross-Build prüft
  alle Python-Abhängigkeiten mit Windows-Markern, Versionen und Python-Anforderungen.
- Mac/Linux auf den gemeinsamen Clientstand nachziehen: Commander-Einstellungen
  und präzisere VAD-Diagnose. Mac-Statuslayout aus 1.7.1 erhalten; die Anpassung
  gegen Windows-Umbrüche nur auf Windows anwenden. Keine neue
  Modell-/Serververarbeitung; gemeinsame Versionsnummer 1.7.4.

## 1.7.3 — Windows, 14.11.2026

- Serverinstallation: Abschlussfunktion bleibt nach der Programmeinrichtung verfügbar;
  Fehler „Complete-CodeUpdate wurde nicht erkannt“ behoben.
- Updatebereinigung nach erfolgreicher Serverprüfung, einschließlich zugeordneter
  Sicherungen vorheriger fehlgeschlagener Abschlussversuche.
- Promptvorlage unter Windows ausdrücklich als UTF-8 lesen; eindeutig erkannte
  beschädigte Standardtexte korrekt vorbelegen, individuelle Anpassungen bewahren.
- Regression mit der ausgelieferten 1.7.2 reproduziert; erfolgreicher Ablauf sowie
  Umlautanzeige, Standardknopf und Konfigurationsübernahme geprüft.

## 1.7.2 — Windows, 14.11.2026

- Sichtbare Vorbereitung und gemeinsamer grafischer Installer im Mac-Aufbau.
- Commander verpflichtend; Vorgabe für neue externe Clients: 10.0.83.140:8185.
- Vorhandene Konfiguration, Modellstufen und Tokens im Wizard übernehmen;
  optionaler zweiter LLM-Commander und alle bisherigen WSL-Speichermodi.
- Downloadfortschritt, sichere Konfigurationsübernahme und erneuter Versuch nach Fehlern.
- Statusanzeigen bleiben einzeilig; Mindestbreite, Ellipse und vollständige Tooltips.
- Produktiver Hersteller-Key privat kompiliert; Deinstaller einschließlich optionaler
  Entfernung der eigenen WSL-Umgebung enthalten.
- Nur Windows neu ausgeliefert. Native Installation testet der Benutzer.

## 1.7.1 — 14.11.2026

- Mac: Nicht registrierte alte App-Sicherungen verhindern den Updateabschluss nicht mehr; echte Registrierungsfehler bleiben sichtbar.
- Verarbeitungsauswahl wieder mit Basis, Gründlich und Sehr gründlich, auch gegenüber älteren Commandern. Modellnamen bleiben als Zusatzinformation erhalten.
- VAD/Pegel/Stilleschwelle nur während einer Aufnahme, eingeklappt oberhalb der technischen Informationen. Clientspezifische Werte bleiben erhalten.
- Linux/WSL und Windows: Sicherungen bei gleichzeitig fehlgeschlagenem Austausch und Rollback erhalten.

## 1.7 — 13.11.2026

- Mac: Client und Server unabhängig aktualisieren. Benötigte Dateien nicht
  ausgewählter Komponenten bleiben aktiv; ersetzte Komponentendateien,
  unbenutzte Versionen und erkannte App-Sicherungen werden bereinigt.
- Linux/WSL: Nach verlorener systemd-Rückmeldung tatsächlichen Dienststart
  abgleichen. Kein wiederholter Neustart; die alte laufende Instanz zählt
  nicht als erfolgreicher neuer Start. Modellbereitschaft weiterhin prüfen.
- VAD und Stilleschwelle bleiben clientspezifisch gespeichert.


## 1.6 — 13.11.2026

- Live-Eingangspegel, Stilleschwelle und VAD-Schalter. Die Werte bleiben pro Client
  erhalten; keine Aufnahme- oder Textspeicherung. CPU-Silero v6 ist offline gebündelt.
- Zeitgetreues Gate mit Vor-/Nachlauf; Nichtsprachabschnitte ohne Whisper-Aufruf,
  stille Abschnitte ohne neue LLM-Dokumentation. Originalaudio bleibt für Diarisierung im RAM.
- Updates ersetzen eigene Programmbäume vollständig und prüfen ihre Aktivierung,
  bevor alte Stände entfernt werden. Modelle und definierte Konfiguration bleiben erhalten.
- Linux fragt Basis, Gründlich und Sehr gründlich auch bei nur einem Modell ab.
- Residente LLMs werden bei identischem Modell trotz anderer Stufenkennung weiterverwendet.
- Einheitliche Version für Mac, Linux und Windows; endgültiger Hersteller-Key privat eingebunden.


## 1.5 — 12.11.2026

- Gemeinsame Version für Mac, Linux und Windows; endgültiger Hersteller-Key privat in kompilierten Binärdateien eingebettet.
- Unabhängige Diarisierungsstrategie: immer geladen, mit Whisper oder seriell. Verschärft seriell ohne erneutes Vorladen nach dem LLM.
- Aufnahmeabschnitte bis zwei Stunden, kontrollierter Abschluss, 256-MiB-Audioanfragen und abgestimmte Verarbeitungszeiten. Bereits erkannter Text bleibt bei Diarisierungsfehlern bearbeitbar.
- Linux: Betriebsartenwahl, bestehende Konfiguration als Vorgabe, unsichtbare Token-Eingabe erklärt, Downloadfortschritt und Modellwiederverwendung.
- Linux: Stufenzuordnung beim Konfigurationscheck, unterstützte Whisper-Downloadquelle, gesicherte Migration eigener alter Dienst-Overrides und korrekter Autostart.
- Mac: eigene verwaiste Modellprozesse bereinigen, Laden beim Installationsabschluss abwarten, Rollback prüfen.
- Windows: gemeinsamer Uninstaller mit Komponenten-, Modell- und Einstellungswahl; offene lokale Record-Fenster werden nicht beendet.
- VAD-/Pegelsteuerung bleibt ausdrücklich zurückgestellt.

## Frühere Entwicklungsnotizen vor 1.5

- Linux-Textinstaller fragt seriellen/parallel vorgehaltenen LLM-Betrieb und
  Whisper auf Abruf (verschärft seriell) ausdrücklich ab. Parallelmodell nach
  denselben Katalogfreigaben wie Windows; nicht verfügbare Profile werden erklärt.
  Sprechertrennung bleibt separat wählbar. Die Auswahl wird zusammengefasst.
- Linux-Updates übernehmen vorhandene Servervorgaben für Modelle, Stufen,
  Betriebsarten, Felder, Prompt, Verbindung und Netzwerkfreigabe. Vorhandene
  Commander-Tokens werden kenntlich gemacht und geschützt weiterverwendet;
  bei Änderung des Remote-Ziels wird dessen alter Token nicht übernommen.
- Nativer Linux-Installer: erkannte Overrides und Verzeichnisregeln des alten
  eigenständigen Commanders vor der Aktivierung sichern und migrieren.
  Fremde Overrides bleiben erhalten; unbekannte Inhalte stoppen die Migration.
  Native Dienste erhalten die benötigten Autostart-Angaben. Die bisherige
  Windows-/WSL-Startsteuerung bleibt erhalten.
- Linux/Windows: `--check-config` löst öffentliche Modellstufen über die
  konfigurierte Modellzuordnung auf. Dadurch bricht die Installation mit
  Gemma als „Gründlich“ nicht mehr durch `KeyError: 'gruendlich'` ab.
- Sprechertrennung erhält eine vom LLM-Betrieb getrennte Auswahl im Mac-,
  Linux- und Windows-Installer: immer geladen, zusammen mit Whisper oder
  seriell. Im verschärft seriellen Ablauf folgt sie auf die abgeschlossenen
  Whisper-Blöcke; kein unnötiges Whisper-Nachladen vor der LLM-Verarbeitung.
- Mac-Installer nennt den gemessenen Speicherbedarf der Sprechertrennung:
  rund 0,6 GB frisch geladen, bis 5,2 GB im kurzen M4-Test; vorläufige
  Arbeitsreserve 6 GB. Keine Obergrenze für längere Gespräche und keine
  Übertragung dieses Messwerts auf NVIDIA-Karten.
- Mac: Beim Commander-Start, Update-Abbruch und Deinstallieren werden eindeutig
  zu dieser Installation gehörende verwaiste Modellprozesse bereinigt. Aktive
  Commander, fremde Prozesse und offene Record-Fenster bleiben geschützt.
- Der Mac-Installer unterscheidet Erreichbarkeit und Modellbereitschaft:
  erreichbare Dienste dürfen ihre konfigurierte Modellladezeit nutzen.
  Abgebrochene Starts beenden eigene Modellprozesse; der Rollback prüft
  Registrierung und Bereitschaft des wiederhergestellten Commanders.
- Linux-Installer: Offizielle OpenAI-Quelle für `whisper/large-v3.pt` zulassen;
  Hugging-Face-Token nur an Hugging Face senden und bei Weiterleitung an einen
  anderen Host entfernen. Modelldateien weiterhin anhand der Prüfsumme prüfen.
- Linux-Token-Abfragen erklären die unsichtbare Eingabe; ein erkannter
  Hugging-Face-Token wird ausdrücklich angezeigt, sein Wert bleibt verborgen.
- Record: Bei fehlgeschlagener Sprecherzuordnung bleibt der bereits erkannte
  Text auch im bearbeitbaren Gesprächsfeld erhalten, einschließlich vorheriger
  ärztlicher Änderungen und Fortsetzungsabschnitte. Keine automatische
  Dokumentation nach dem Fehler; klarer Hinweis zur erneuten Verarbeitung.
- HTTP-Fehler der Sprecherzuordnung nennen den betroffenen Schritt und Status,
  ohne den möglicherweise vertraulichen Inhalt der Serverantwort anzuzeigen.
- Mac: Record- und Connect-Starter beenden sich nach ihrem letzten eigenen
  Kindprozess. Dadurch bleiben nach dem Schließen keine alten Starter aktiv,
  die nach einer Neuinstallation auf entfernte Programmdateien zugreifen.
- Startfehler nennen eine technische Fehlerkennung ohne Patientendaten;
  ein Starter mit inzwischen entferntem Installationsverzeichnis beendet sich
  nach einem verständlichen Hinweis.

## Linux 1.4.4 – 2026-11-12

- Root-Start für reine Serverinstallation freigegeben; Desktop-Client weiter als angemeldeter Benutzer.
- Endgültiger Hersteller-Key in Connect und nativer Direktzugriffs-Bibliothek, ohne Klartext-Key-Datei im Paket.
- Textbasierte Deinstallation mit getrennter Auswahl für Komponenten, Modelle und Einstellungen; Schutz offener Aufnahmen und fremder Dienste.
- Produktcode-Anleitung und alle gemeinsamen Record-Änderungen aus 1.4.4 übernommen.
- Linux-Binärdateien und 20 Installer-/Deinstallationsprüfungen auf Ubuntu 24.04 erfolgreich; vollständiger Desktop-/GPU-Installationslauf bleibt Benutzerabnahme.

## Mac 1.4.4 – 2026-11-12

- Fehlende Record-/Connect-Starter bei der Installation korrigiert; Paketprüfung vor Downloads.
- Endgültiger Hersteller-Key privat in Connect und native Direktzugriffs-Bibliothek eingebunden; keine Klartext-Key-Datei im Paket.
- Regelmäßige Commander-Statusabfrage für Standby, Laden und Bereitschaft.
- T2med-Produktcode-Anleitung mit Bildern; Einrichtung über den aktivierten KienzleDoku-Eintrag.
- Deinstallation von Client, Server oder beiden im Assistenten; Modelle und Einstellungen standardmäßig behalten, aktive Aufnahmen schützen.
- Vorhandene Windows-/Linux-Pakete 1.4.3 bleiben unverändert.

## Windows und Linux 1.4.3 – 2026-11-11

- Gemeinsames Windows-Setup für Client, Server oder beides; eigener Python-Client
  und Windows-Server-Assistent 1.13 mit Modellstufen, Feldern und Prompt.
- Textbasierter Ubuntu-24.04-Installer für Client, Server oder beides.
- Server: Qwen3.5 4B als Basis, explizite Zuordnung der installierten Modelle,
  optionaler Token-Schutz und Whisper auf Abruf; bestehende Parallelprofile bleiben erhalten.
- T2med-Anleitung und kopierbare vollständige URL am Installationsende.
- Windows-Aufnahmefenster im privaten WebView2-Modus.
- Neue Artefakte mit Prüfsummen; vorhandene Versionen werden nicht überschrieben.
- Mac-Installationspaket 1.4.2 bleibt erhalten; keine Änderung der laufenden Installation.


## Record und Installer 1.4.2 – 2026-11-11

- Neue Auslieferung mit erhöhter Versionsnummer. Der Mac-Build verweigert
  künftig das Überschreiben einer bereits vorhandenen DMG-Version.
- „Fenster schließen und verwerfen“ zeigt auf dem Mac den nativen
  Bestätigungsdialog; Abbrechen erhält die offene Aufnahme.
- Native Bearbeiten-Menüs für Installer und Record: Einfügen per ⌘V sowie
  Kopieren, Ausschneiden, Alles auswählen und Rückgängig.
- Vorhandene Hugging-Face-Tokens werden im Passwortfeld des Installers
  vorbelegt. Nach erfolgreicher Serverinstallation wird das Token getrennt
  von der Konfiguration in einer privaten Datei für spätere Installationen
  hinterlegt; keine Token-Ausgabe in Protokollen.
- Record und Connect erhalten getrennte Mac-Starter mit unterschiedlichen
  ausführbaren Programmkennungen und einer Beschreibung des lokalen
  Netzwerkzugriffs für die macOS-Berechtigungsabfrage.
- Connect-Transportfehler nennen eine feste technische Fehlerkategorie ohne
  URLs, Tokens oder Patientendaten. Ein gescheiterter Leseabruf erzeugt keine
  irreführende Warnung über einen unklaren Schreibausgang mehr.
- Connect-Patientenabruf nach dem Austausch der Mac-Starter im Praxistest
  durch den Benutzer bestätigt.

## Record und Installer 1.4.1 – 2026-11-11

- Startfehler bei ausgeschaltetem Commander-Token behoben: Eine leere private
  Token-Datei bedeutet „kein Token“ und wird nicht mehr als ungültig abgelehnt.
- Mac-Connect-Aufruf korrigiert: Ein abschließender Zeilenumbruch der
  URL-Übergabe verhindert den Start nicht mehr; eingebettete Steuerzeichen
  bleiben gesperrt. Der Mac-Starter sendet die URL ohne zusätzlichen Umbruch.
- T2med-Startadresse auf der Installer-Abschlussseite vollständig umgebrochen,
  ohne Scrollbalken oder abgeschnittene Zeichen; Kopieren erhält die exakte URL.
- Knopf „Fenster schließen“ am unteren Ende der abgeschlossenen Installation.

## Record und Commander 1.4.0 – Mac-Teststand, 2026-11-11

- Grafischer Mac-Installer mit eigener Laufzeit, kombinierter Client-/Serverinstallation,
  Modellauswahl und aktiver Zuordnung zu Basis, Gründlich und Sehr gründlich.
- Commander verwaltet Prompt und Feldauswahl; EKG, SON und NOT ergänzen die
  bisherigen Felder. Aktiver Prompt in den technischen Informationen von Record.
- Patientendaten ausschließlich im RAM des offenen Record-Fensters; kein
  Sitzungsarchiv. Warnung vor Patientenverwechslung bei einem zweiten Aufruf.
- Fortgesetzte Aufnahmen erhalten eine Abschnittsmarkierung. Logo auf 66 Prozent
  bei unveränderter umgebender Fläche; eine einzelne Stufe benötigt kein Menü.
- Verschärfter serieller Modus: Whisper beim ersten Audioblock laden, zwischen
  Blöcken behalten und nach Entladen für die weitere Verarbeitung kalt lassen.
- Optional eigener LLM-Commander. Commander-Token standardmäßig aus; keine
  HTTPS-Erweiterung in diesem Schritt. Demo-Hersteller-Key bleibt aktiv.
- Windows-Server-Installer 1.12 unverändert. Praktische Mac-Abnahme steht an;
  weitere Installer-Vereinheitlichung nach diesem Test.

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

- Rückmeldung „EKG erscheint in T2med als SON“ weiter offen: Synthetischer
  Test vom echten Formular-Handler bis zum serialisierten FHIR-Auftrag
  bestätigt EKG → EKG und Sonografie → SON, auch wenn nur EKG ausgefüllt ist.
  Laut Benutzer war Sonografie beim Vorfall leer; die technischen Protokolle
  zeigen strukturierte Übernahmen. Die tatsächliche Darstellung in
  T2med muss anhand eines gezielten Testfalls weiter eingegrenzt werden;
  keine erneute Übertragung vorhandener Patientendokumentation.
- Für den nächsten Durchlauf vorgemerkt (Rückmeldung vom 11.11.2026,
  noch nicht umgesetzt): Die Dienststatusfelder in Record aktualisieren sich
  im praktischen Test nicht. Den laufenden Statusabruf und die Anzeige prüfen
  und korrigieren, insbesondere für Whisper und LLM im seriellen Modus.
  Ohne Neuladen des Fensters den tatsächlichen Commander-Zustand anzeigen:
  „Standby“ in Gelb, „wird geladen“ in Gelb und bereit in Grün.

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
