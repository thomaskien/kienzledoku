# Änderungsprotokoll

Alle wesentlichen Änderungen an Kienzledoku werden in diesem Dokument
festgehalten. Das Format orientiert sich an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unveröffentlicht]

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
