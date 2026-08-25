# Änderungsprotokoll

Alle wesentlichen Änderungen an Kienzledoku werden in diesem Dokument
festgehalten. Das Format orientiert sich an
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unveröffentlicht]

- Noch keine Änderungen.

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
