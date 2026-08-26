# Kienzlefon AI → Kienzledoku 1.2.1

Dieses Dokument definiert die vorbereitete Nahtstelle zwischen den bereits
vorhandenen Kienzlefon-AI-Diensten und der T2med-Übergabe in Kienzledoku.

## Zielkette

```text
CoreAudio-Mikrofon → lokale WAV-Blöcke
  → Kienzlefon ASR Final-Block (Port 8179)
  → optionale Diarisierung (Port 8183)
  → Kienzlefon LLM (Port 8080)
  → validiertes Kienzledoku-JSON
  → ärztliche Sichtung/Korrektur
  → eine atomare T2med-FHIR-Transaktion
```

Der Streaming-Gateway auf Port 8178 bleibt die Telefonie-Abstraktion von
Kienzlefon AI. Für die aus WhisperDoku 6.2 übernommene Verarbeitung natürlicher
Sprechpausen ist der bestehende Final-Block-Endpunkt auf Port 8179 die
maßgebliche ASR-Schnittstelle. Es wird kein weiteres Whisper-Modell geladen.

## Verbindlicher Dokumentationsvertrag

Zwischen LLM und Kienzledoku wird ausschließlich dieses JSON-Objekt übergeben:

```json
{
  "anamnese": "",
  "befund": "",
  "therapie": "",
  "prozedere": ""
}
```

Regeln:

- Alle vier Schlüssel müssen genau einmal vorhanden sein.
- Zusätzliche Schlüssel werden abgelehnt.
- Werte sind Zeichenketten oder `null`; `null` wird zu einer leeren
  Zeichenkette normalisiert.
- Markdown, erläuternder Text und erfundene Angaben sind nicht zulässig.
- Die Reihenfolge für Anzeige und Freitext ist Anamnese, Befund, Therapie,
  Prozedere.
- Die Validierung erfolgt in `kienzledoku_document.py`; die Prompt-Vorlage liegt
  in `prompt_documentation.txt`.

## T2med-Ausgabe

Nach der Sichtung entscheidet die konfigurierte Ausgabeform:

- `structured`: bis zu vier getrennte Observation-/Procedure-Ressourcen.
- `single`: genau eine Freitext-Observation mit den nicht leeren Abschnitten
  und dem konfigurierten Kürzel, beispielsweise `A`, `KI` oder `AI`.

Beide Varianten werden als FHIR-Transaction-Bundle an die FHIR-Basis-URL
geschickt. Eine teilweise Übernahme wird von Kienzledoku nicht als Erfolg
akzeptiert.

## Umgesetzte Zusammenführung

Kienzledoku verbindet die Komponenten über folgende getrennte Adapter:

1. Der ASR-Adapter übernimmt die Final-Block-Semantik aus
   Kienzlefon WhisperDoku 6.2 und liefert abgeschlossene Blöcke während der
   laufenden Aufnahme an das sichtbare Live-Transkript.
2. Der optionale Diarisierungsadapter ergänzt Sprecherzuordnungen, ohne den
   Wortlaut des Transkripts zu verändern.
3. Der LLM-Adapter sendet Transkript und `prompt_documentation.txt` an den
   residenten Dienst auf Port 8080 und validiert die Antwort strikt mit
   `parse_documentation_json`.
4. `kienzledoku_speech.py` kapselt Aufnahme und Hintergrundprozess, meldet das
   verwendete CoreAudio-Eingabegerät, verwirft temporäre WAV-/JSON-Dateien und
   übergibt nur das validierte Ergebnis an die Oberfläche.
5. Das diarisiert dargestellte Sprechertranskript bleibt editierbar. Ein
   erneuter LLM-Lauf verwendet genau diesen bearbeiteten Text und wiederholt
   weder Aufnahme noch ASR oder Diarisierung.
6. Eine fortgesetzte Aufnahme wird separat verarbeitet und an den bereits
   vorhandenen Sprechertext angehängt. Der vorhandene Text wird nicht gelöscht;
   das LLM erhält danach den vollständigen, zusammengeführten Gesprächsblock.
7. Erst nach manueller Sichtung werden die validierten Felder an
   `write_documentation` übergeben. Es gibt keinen zusätzlichen
   Bestätigungsdialog; nach erfolgreicher T2med-Transaktion endet die Sitzung
   und das native Kienzledoku-Fenster wird geschlossen.

Das sichtbare Fenster ist ein kleiner lokaler WebKit-Container ohne URL- oder
Browserleiste. WebKit zeigt nur den Zustand und die Eingabefelder an. Die
Audiodaten werden nicht über WebKit transportiert; der ASR-Prozess liest sie
direkt per `sounddevice` aus CoreAudio.

Für Apple-Silicon-Macs mit mindestens 32 GB enthält das Repository nun den
eigenständigen Installer [`local-ai-macos`](local-ai-macos/README.md). Er stellt
kompatible lokale Dienste für Qwen/llama.cpp, Whisper/MLX und pyannote/MPS
bereit, verändert aber weder einen vorhandenen Kienzlefon-AI-Installer noch
dessen Server-Snapshots. Alternativ können weiterhin vorhandene Dienste auf
demselben Mac oder im Praxisnetz verwendet werden.

Die **empfohlene Betriebsarchitektur** verwendet einen dedizierten
Ubuntu-x86_64-Server mit NVIDIA/CUDA. Der getrennte Installer
[`server-linux`](server-linux/README.md) richtet dort LLM,
WhisperLiveKit/Faster-Whisper und pyannote als systemd-Dienste ein und ergänzt
den für Kienzledoku erforderlichen Final-Block-Endpunkt auf Port 8179. Der
T2med-Mac bleibt dabei der Client; der vollständig lokale Apple-Silicon-Betrieb
ist eine optionale Alternative.

## Konfigurierbare Dienstziele

Der Kienzledoku-Installer fragt zuerst den erlaubten T2med-FHIR-Host und danach
ASR, Diarisierung und LLM getrennt ab. Die drei KI-Dienste dürfen auf demselben
Mac, auf verschiedenen Macs oder gemischt lokal und im Praxisnetz laufen. Bei
einer Erstinstallation werden folgende Ziele vorgeschlagen:

- T2med-FHIR-Host: `10.0.83.120` (änderbarer Vorschlag, keine feste Codegrenze)
- ASR: `http://127.0.0.1:8179`
- Diarisierung: `http://127.0.0.1:8183`
- LLM: `http://127.0.0.1:8080`

Nach der ASR-Eingabe wird ihr Host als Vorschlag für die Diarisierung verwendet;
deren Host wird entsprechend für das LLM vorgeschlagen. Bei Upgrades werden
stattdessen vorhandene Einzelwerte beibehalten. Die lokale Datei
`~/Library/Application Support/Kienzledoku/config.json` enthält ausschließlich
den erlaubten T2med-FHIR-Host und diese Dienstadressen, keine Patienten-,
OAuth- oder API-Daten. Die Oberfläche prüft und zeigt die Erreichbarkeit aller
drei Dienste separat an. Dieser Installer-Pfad wird beim Anwendungsstart
ausdrücklich übergeben; eine vorhandene Datei hat Vorrang vor geerbten
Dienstvariablen. Die
tatsächlich geladene Quelle ist in den technischen Informationen sichtbar.
