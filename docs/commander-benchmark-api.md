# Commander 1.8.1: Vorbereitung für Kienzlebench

Diese Ausgabe erweitert ausschließlich die Commander-Schnittstelle. Testschleifen,
Bericht, Zwischenablage, Temperaturverlauf und Kienzlebench-Programm folgen später.
Die bisherigen Dokumentations-, ASR-, Health- und Profilendpunkte bleiben erhalten.
Transportverschlüsselung ist unverändert separat vorgesehen.

## Herkunft und Hardware

Alle GET-Antworten sind JSON, `Cache-Control: no-store`. Sie unterliegen der
vorhandenen Commander-Authentifizierung. Der normale Betrieb bleibt standardmäßig
ohne Token möglich. Daten betreffen den ausführenden Server, nicht den Browser.

| GET-Endpunkt | Inhalt |
| --- | --- |
| `/v1/runtime/capabilities` | Commander-/API-Version, Fähigkeiten, effektive Residenz-/Cacheeinstellungen |
| `/v1/runtime/inventory` | Alle verwalteten Modelle, Aliasse und getrennte Profile; installierte/fehlende Dateien, Standard, geladen, resident, Parallelfreigabe |
| `/v1/runtime/hardware` | CPU, RAM, Mainboard, System, GPU und System-/Modelllaufwerke |
| `/v1/runtime/temperatures` | Ausschließlich aktuelle CPU-/GPU-Sensorwerte mit Quelle und Zeitpunkt |

Antworten enthalten `schema_version: 1` und `context` mit Rollen, Commander-Version
und konfiguriertem GPU-Index. Andere Commander werden als `remote_llm` bzw.
`remote_diar` mit Quelle und einer getrennten Antwort oder `status: unavailable` ausgegeben. Eine
Weiterleitung wird nicht verkettet. Lokale und entfernte Messzeiten nicht mischen.
Keine Zugangsdaten, Seriennummern oder Hardware-UUIDs werden ausgegeben.

Das Hardwareinventar enthält `system`, `cpu`, `memory`, `board`, `storage`, `gpus`.
Größen enden auf `_bytes`. Jede Gruppe benennt die Quelle und eine `unavailable`-
Zuordnung für nicht ermittelbare Felder. `null` bedeutet unbekannt, nicht null Byte.
`storage.role` unterscheidet `system` und `model:<Index>`; zugehörige Dateinamen
stammen aus den bekannten Modellpfaden. Physische Kapazität und Volume-Freiplatz
sind getrennt. Netzwerk-, virtuelle und physische Laufwerke bleiben unterscheidbar.
Bei WSL stammen Gastlimits aus Linux, physische Hostangaben separat aus Windows-CIM,
soweit erreichbar. Eine virtuelle WSL-Platte wird nicht als physische SSD ausgegeben.

Mac-Unified-Memory wird ausdrücklich als geteilter Speicher bezeichnet; GPU- und
RAM-Größe dürfen nicht addiert werden. macOS liefert keinen exakten mit Linux
`MemAvailable` gleichwertigen Zähler: `available_bytes` bleibt dort `null`,
`free_plus_inactive_bytes` ist eine getrennt benannte Systemzählung.

Temperaturen stehen in `sensors`: `kind`, `id`, `name`, `value`, `unit: celsius`,
`source`, `measured_at`, `status`, `reason`. Fehlende Werte bleiben `null` mit Grund.
Linux liest bekannte CPU-/GPU-hwmon-Sensoren und NVIDIA über `nvidia-smi`.
WSL liefert nur tatsächlich zugängliche Sensoren. macOS fragt Apple-SMC-Sensoren
lesend über IOKit ab (`source: apple-smc`); der Adapter wurde auf einem M4 geprüft.
Nicht zugängliche Sensoren bleiben unbekannt. Keine erhöhten Rechte, Zusatzdienste
oder Sensorprogramme werden eingerichtet. Pro Rechner zeigt Record den höchsten
aktuellen GPU-Sensorwert, mit Commander-Adresse im Tooltip. Gleich konfigurierte
Commander-Adressen erscheinen einmal, fehlende oder über 30 Sekunden alte Werte gar nicht.

Die Sensorabfrage startet nur auf Anfrage, ohne Hintergrundthread, Verlauf oder
alte Ersatzwerte. Externe Befehle haben höchstens zwei Sekunden Laufzeit;
Temperatur-/Inventar-Befehle teilen ein Budget von drei/acht Sekunden. Maximal zwei
Hardwareabfragen laufen gleichzeitig. Ferne Abfragen haben zehn Sekunden Timeout.
Hardwareinventar wird nicht bei jeder Temperatur- oder normalen Statusabfrage erzeugt.

## Modelle und Einstellungen

`models` enthält stabile `id`, `model_id`, `label`, `aliases`, `backend`,
`quantization`, `context`, `context_per_slot`, `slots`, `kv`, `installed`, `available`,
`reason`, `default`, `resident`, `loaded`, `parallel_available`, `parallel_reason`.
Aliasse desselben Modellprofils werden zusammengefasst. Unterschiedliche Kontext-/
Slot-/KV-Profile bleiben getrennt. Keine Suche über fremde Modellverzeichnisse.
Eine vorhandene Datei allein beweist noch keinen erfolgreichen Modellstart.

`effective_settings` in den Capabilities benennt die gespeicherte Betriebspolitik,
Whisper auf Abruf und die unabhängige Diarisierungsstrategie. Die Benchmarkantwort
benennt zusätzlich den temporären Modus. Diarisierung wird nicht als versteckter
Test ausgeführt; ihre vorhandene Residenzstrategie bleibt wirksam.

## Begrenzte Benchmarkkontrolle

Die Benchmarksteuerung verwendet denselben optionalen Tokenschutz wie alle anderen
Commander-Endpunkte. Ist der Schutz ausgeschaltet (Standard), ist kein Token
erforderlich. Ist er eingeschaltet, wird der konfigurierte Token wie bisher als
`Authorization: Bearer …` übergeben, nicht in der URL. Es gibt keinen separaten
Benchmark-Token und keine zusätzliche Aktivierungspflicht.

1. `POST /v1/benchmark/session`, JSON:
   `{"model_id":"<id aus inventory>","mode":"serial","lease_seconds":120}`.
   `mode` ist `serial` oder `parallel`; Parallelbetrieb nur bei geprüftem Profil.
   Kein implizites Standardmodell, kein beliebiger Dateipfad. ASR-only-Server:
   `model_id: null`, `mode: serial`. Einen entfernten LLM-Commander separat steuern.
2. Die Antwort enthält die Sitzungs-`id`. Für alle weiteren Aufrufe diese als
   `X-Kienzledoku-Benchmark-Session` senden.
3. `POST /v1/benchmark/session/keepalive` mit `{}` verlängert die Lease.
   Gültig sind 15–300 Sekunden. Laufzeitsteuerung/30-Minuten-Schleife liegt beim Client.
4. `GET /v1/benchmark/session` liefert Zustand, geladenes Modell, Zeit bis Ablauf,
   Modellwechsel, Cachebedingungen und gegebenenfalls Wiederherstellungsfehler.
5. `POST /v1/benchmark/session/end` mit `{}` beendet die Sitzung. Neue Aufträge
   werden abgewiesen, eigene wartende Aufträge verworfen, aktive Aufträge beendet
   und anschließend die vorherige Modellvorhaltung wiederhergestellt. Status
   `restoring` bis `completed` abfragen. Derselbe Endaufruf ist wiederholbar.

Start während laufender/ausstehender Arbeit oder Modellwechseln meldet Konflikt.
Normale Aufträge während einer exklusiven Sitzung erhalten `busy`; sie werden
nicht unter Benchmarkparametern verarbeitet. Bei Verbindungsverlust endet die
Sitzung nach Lease-Ablauf. Backend-/Ladezeitlimits begrenzen den Nachlauf; ein
Wiederherstellungsfehler wird separat gemeldet. Keine Konfigurationsdatei wird
umgeschrieben. Ein Commander-Neustart startet die gespeicherte normale Politik.

## Rohprompt, Whisper und Messwerte

`POST /v1/benchmark/chat/completions` akzeptiert `model_id`, frische `request_id`,
`messages` mit `role`/`content` sowie begrenzte Samplingparameter `temperature`,
`max_tokens`, `top_p`, `top_k`, `min_p`, `repeat_penalty`, `seed` und optional
`response_format: {"type":"json_object"}`. Prompts werden ohne Ergänzung des
Dokumentationsprompts weitergegeben. Backend-Chattemplate und Backendkonfiguration
bleiben dieselben; das ist keine Zusage tokenizeridentischer historischer Läufe.

`POST /v1/benchmark/asr/final-block` verwendet den vorhandenen Multipartvertrag.
Eine neue `Idempotency-Key` ist Pflicht. Nur synthetische Benchmarkdaten verwenden.
Nicht vorhandene Modelle werden abgewiesen; ein fehlgeschlagener Lauf verwendet
kein Ersatzmodell. Neue Wiederholungen brauchen neue IDs. Eine bereits verwendete
ID wird abgewiesen, statt eine alte Antwort als neue Berechnung auszugeben.
Bis zu 4096 unterschiedliche Aufträge pro Sitzung; normale Queue-/Speicherlimits
bleiben wirksam. Serielle und parallele Vorhaltung sind getrennt von tatsächlich
überlappender Inferenz: `inference_started_at` und `completed_at` belegen Überlappung.

Die Antwort enthält `benchmark`; `GET /v1/benchmark/jobs/<request_id>` liefert
nur Messmetadaten, keinen Prompt, kein Audio und keinen Ergebnistext. Hier sind
auch nachträgliche Rückwechselzeiten sichtbar. Auftragsmetadaten unterliegen dem
vorhandenen begrenzten Ergebnis-Cache des Commanders.

- Zeitbasis `server_monotonic_seconds`: `submitted_at`, `inference_started_at`,
  `completed_at`; niemals zwischen unterschiedlichen Rechnern subtrahieren.
- `queue_seconds`, `model_preparation_seconds`, `inference_seconds`,
  `response_seconds`, `return_seconds`, `return_complete` getrennt.
- `model_changes` nennt Rolle, Laden/Entladen, Phase, Anfang, Dauer und Erfolg.
  Wechsel vor dem ersten Auftrag sind zusätzlich in der Sitzungsantwort sichtbar.
- Historischer LLM-Hauptwert: tatsächliches LLM-Laden plus Inferenz bis zur
  vollständigen Backendantwort; ASR-Wechsel und Rückkehr nicht hinzurechnen.
  HTTP-Übertragung zum Benchmarkclient ist ein separater clientseitiger Messwert.
- Backend-`timings` und `usage` werden nur übernommen, soweit numerisch geliefert.
  Der nicht streamende Pfad liefert keinen echten TTFT: `ttft_seconds: null`
  mit `ttft_reason: non_streaming_backend`.
- `cache_prompt` wird immer `false`. OS-Dateicache bleibt unverändert/unbekannt;
  ein neu geladenes Modell beweist keinen SSD-Kaltstart. Whisper-Modellcache,
  KV-Typ und Modellresidenz sind getrennt. Keine systemweite Cacheleerung.

Bei einem zweigeteilten ASR-/LLM-System beide Hosts und beide Sitzungen getrennt
im späteren Bericht dokumentieren. Kein Testaudio und keine historische
Patientendokumentation werden mit diesem Installer ausgeliefert.

## Prüfungen und Beispiele

Hardware- und Benchmark-Vertragstests liegen in `tests/test_commander_hardware.py`
und `tests/test_commander_benchmark.py`; die Serverkopie wird in einem eigenen
Prozess getestet. Reale Sensormessungen sind von simulierten Wechseltests getrennt.
Ein reales bereinigtes Mac-Inventar liegt unter
[examples/commander-hardware-macos.json](examples/commander-hardware-macos.json).
Daraus kann der spätere Textbericht CPU, RAM, Mainboard/Mac-Modell, SSD, GPU sowie
fehlende Angaben vollständig darstellen. Eine tatsächliche Windows-/WSL-Hardware-
und GUI-Abnahme erfordert weiterhin den Windows-Testrechner.
