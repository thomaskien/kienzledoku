# Rückgabe: Vorbereitung für Kienzlebench, Commander 1.8

Stand: 16.11.2026. Umsetzung und Installer fertig; keine GitHub-Veröffentlichung
und keine Aktualisierung laufender Installationen in diesem Auftrag.
Kienzlebench selbst, sein Bericht/UI und Transportverschlüsselung bleiben außerhalb
von 1.8. Die offene native Windows-Abnahme und Sensorgrenzen sind unten benannt.

## Ausgangspunkt und Dateien

Ausgangspunkt ist der veröffentlichte 1.7.6-Commit
`eebe8930613637f4110fcbe6501a9ad39278c84e`, Branch `release/1.8`, isolierter
Arbeitsstand `/private/tmp/kienzledoku18-release`. Der umfangreiche geänderte
Entwicklungsbaum `github-release` wurde nicht zurückgesetzt. Die separat
vorbereiteten Auditkorrekturen A01/A02/A05/A06/A07 wurden nach Review übernommen.
Eine allgemeine LAN-Tokenpflicht aus A03 wurde ausdrücklich nicht übernommen.

Sol wurde entsprechend den persönlichen Regeln ausschließlich über
`codex-sol-worker` versucht. Der separate Account unterstützt das konfigurierte
Modell `gpt-5.6-sol` nicht. Keine Account-/Loginänderung, keine nativen Ersatzagents;
Implementierung und abschließendes Review durch den Lead.

| Dateien | Inhalt |
| --- | --- |
| `kienzledoku_commander/hardware.py` | Begrenzte Hardware- und aktuelle Sensorabfragen |
| `benchmark.py`, `benchmark_api.py` | Inventar, Capabilities, authentifizierte Sitzung, Rohprompt und Messmetadaten |
| `scheduler.py`, `runtime.py`, `config.py`, `api.py` | Temporäre Modellpolitik, Wiederherstellung, Instrumentierung, additive API |
| `server-windows/linux/runtime/kienzledoku_commander/` | Tatsächlich ausgelieferter Linux-/WSL-Pfad; gemeinsame Änderungen identisch |
| `installer/core.py`, `server-windows/linux/install_server.py` | Verwalteter Modellkatalog und bekannte ASR-/Diarisierungsmodellpfade |
| `installer/runtime_contract.py`, `runtime-variants.json` | Buildprüfung gemeinsamer Quellen und ausdrücklich geprüfter Plattformunterschiede |
| `tests/test_commander_benchmark.py`, `test_commander_hardware.py` | Fehler-, Ablauf-, Hardware- und API-Verträge |
| `server-windows/tests/test_commander_benchmark_profiles.py` | Tatsächlicher Serverkatalog, Aliasse und explizite Modellwahl |

## Vertrag, Beispiele und Kompatibilität

Vollständiger Vertrag: [Commander-API](commander-benchmark-api.md).
Die Endpunkte sind additiv. Alte Clients benutzen weiter ihre bisherigen
Status-/Profil-/Dokumentationsendpunkte. Ein späterer Benchmarker muss gegen
ältere Commander zunächst die Capabilities prüfen; fehlender Endpunkt bedeutet
fehlende Unterstützung und keine stillschweigende Ersatzmessung.

| Endpunkte | Zweck / Zugang |
| --- | --- |
| GET `/v1/runtime/hardware`, `/temperatures`, `/inventory`, `/capabilities` | Vorhandene optionale Commander-Authentifizierung; aktuelle Werte bzw. `null` mit Grund |
| POST `/v1/benchmark/session` | Explizites Modell und serial/parallel; aktivierter Bearer-Tokenschutz erforderlich |
| GET `/v1/benchmark/session` | Temporärer Modus, geladenes Modell, Lease, Wiederherstellung |
| POST `/v1/benchmark/session/keepalive`, `/end` | `{}`; Sitzungs-ID im Header, Ende wiederholbar |
| POST `/v1/benchmark/chat/completions`, `/asr/final-block` | Rohprompt bzw. bisheriger ASR-Multipartvertrag, immer frische Auftrags-ID |
| GET `/v1/benchmark/jobs/<id>` | Nur Messmetadaten, keine Inhalte |

Beispielaufrufe ohne tatsächliche Zugangsdaten, wobei `SERVER` auf den ausführenden
KI-Rechner zeigt und `COMMANDER_TOKEN` privat gesetzt ist:

```bash
SERVER=http://127.0.0.1:8185
curl -fsS "$SERVER/v1/runtime/capabilities"
curl -fsS "$SERVER/v1/runtime/hardware"
curl -fsS "$SERVER/v1/runtime/temperatures"
curl -fsS -H "Authorization: Bearer $COMMANDER_TOKEN" "$SERVER/v1/runtime/inventory"
curl -fsS -H "Authorization: Bearer $COMMANDER_TOKEN" -H 'Content-Type: application/json' \
  -d '{"model_id":"gemma12_q8","mode":"serial","lease_seconds":120}' \
  "$SERVER/v1/benchmark/session"
```

Die Modell-ID aus `inventory` verwenden; `gemma12_q8` ist nur ein Linux-Katalogbeispiel.
Auf einem authentifizierten Commander auch die ersten drei GETs mit Bearer-Header
aufrufen. Für Folgeschritte die zurückgegebene ID als
`X-Kienzledoku-Benchmark-Session` senden. Messzeiten sind monotone Serverzeiten;
Zeitpunkte unterschiedlicher Server nicht verrechnen. Fehler sind JSON mit
`error.code`/`message`, darunter `busy`, `invalid_request`, `conflict`,
`backend_failure` und `benchmark_auth_required`. Keine beliebigen Shell-/Dateipfade.

## Hardware und aktuelle Temperaturen

Reale, reine Leseabfragen ohne Benchmark:

| Plattform | Nachweis | Grenze |
| --- | --- | --- |
| Mac M4 / 32 GiB | CPU/Mac-Modell, Kerne/Threads, Unified Memory, echte APPLE SSD AP2048Z über APFS-Zuordnung | CPU/GPU-Temperaturen derzeit `null`, `no_supported_unprivileged_sensor`; keine Zusatzkomponente automatisch eingerichtet |
| Linux / Ryzen 9 5900X / RTX 3090 | CPU über proc/sysfs, Board/DMI, Speicher und Datenträger; CPU-hwmon und GPU-NVIDIA-Temperatur | Verfügbarkeit hängt von Rechten/Sensoren des Commander-Prozesses ab |
| Windows / WSL | WSL-Gast/Windows-CIM-Vertrag und Mehr-GPU-Fälle simuliert; Windows-Paket erstellt | Kein nativer Windows-/WSL-Hardwarelauf in diesem Auftrag |

Beispiel tatsächlich erfasster Linux-Sensorwerte am 16.11.2026: CPU-Sensoren
30,0 / 30,75 / 28,75 °C und GPU 44 °C. Das sind einzelne Prüfmessungen,
keine aktuellen Betriebswerte und kein Commander-Verlauf. Neue Abfragen lesen neu.
Fehlende Messungen liefern beispielsweise:

```json
{"kind":"cpu","value":null,"unit":"celsius","status":"unavailable",
 "reason":"no_supported_unprivileged_sensor","source":"Darwin"}
```

Ein vollständiges reales Adapterbeispiel steht unter
[examples/commander-hardware-macos.json](examples/commander-hardware-macos.json).
Daraus ableitbarer Textkopf (erfasste Prüfdaten, keine Benchmarkresultate):

```text
KIENZLEBENCH — HARDWARE-PRÜFBEISPIEL
System: macOS / Apple Silicon, Mac16,10
CPU: Apple M4, 10 Kerne / 10 logische Prozessoren
RAM: 32 GiB installiert, Unified Memory; verfügbar: exakter Zähler nicht verfügbar
Mainboard/Systemkennung: Apple / Mac16,10; Firmware: nicht verfügbar
SSD: APPLE SSD AP2048Z, physische Kapazität 2.001.111.162.880 Byte
Modell-Volume: APFS, Größe und Freiplatz separat in der JSON-Antwort
GPU: Apple M4, geteilter 32-GiB-Speicher; nicht zum RAM addieren
Temperaturen: ohne unterstützten Mac-Sensoradapter nicht verfügbar
Benchmark: nicht ausgeführt
```

WSL-Host-RAM und sichtbarer Gast-RAM werden getrennt geprüft. Netzwerkpfade werden
nicht als SSD ausgegeben. Die Zuordnung zu ASR-, Diar- und LLM-Modellen ist über
`storage[].models` möglich. Fehlende Feldwerte bleiben mit Herkunft/Grund sichtbar.
Es werden keine Seriennummern oder Hardware-UUIDs benötigt oder ausgegeben.

Externe Sensor-/Inventarbefehle: maximal zwei Sekunden einzeln, drei/acht Sekunden
Gesamtbudget. Auch potentiell blockierende Dateisystemabfragen laufen in einem
zeitlich begrenzten Kindprozess. Maximal zwei gleichzeitige Hardwareabfragen,
keine dauerhaften Messthreads, Temperaturarchive oder letzten Ersatzwerte.
Die Inventarisierung wird nicht durch normale Status-/Temperaturabfragen wiederholt.

## Benchmark, Zeitwerte und Cache

Explizite Modellwahl wird für die Sitzung festgehalten, unabhängig vom Standard.
Stufenaliase desselben Profils werden zusammengefasst; unterschiedliche Profile
bleiben unterscheidbar. Parallelbetrieb benötigt eine vorhandene Freigabe.
Normale Aufträge erhalten während exklusiver Benchmarkkontrolle `busy`.
Sitzungsbeginn während aktiver/ausstehender Verarbeitung wird abgewiesen.

Rohprompts werden nicht mit dem Produktivprompt ergänzt. Die bestehende
Backend-Chatvorlage bleibt wirksam. Fehler lösen keinen Modellfallback aus.
Wiederholte IDs werden abgewiesen; eine neue ID führt neue Verarbeitung aus.
Serielle Wechsel und echte parallele ASR-/LLM-Inferenz wurden simuliert geprüft.
Die vorhandene Diarisierungsstrategie bleibt erhalten, ohne zusätzliche Diartests.

Queue, Modellwechsel, Inferenz, vollständige Backendantwort und Rückwechsel werden
getrennt gemessen. TTFT ist im nicht streamenden Pfad ausdrücklich unbekannt.
Nur tatsächlich gelieferte numerische Backend-Token-/Zeitwerte werden übernommen.
Der Benchmarker kann den historischen LLM-Hauptwert aus LLM-Laden und Inferenz
bilden; ASR und Rückkehr getrennt lassen. HTTP-Zeit beim Client separat messen.

Prompt-Cache ist aus; OS-Dateicache bleibt unbekannt/unverändert. Whisper-Cache und
KV-Typ werden getrennt benannt. Modellneuladen ist kein Nachweis eines SSD-Kaltstarts.
Die Sitzung ändert keine Dateien; Ende/Lease-Ablauf stoppt neue Arbeit, lässt
begonnene Arbeit innerhalb der vorhandenen Timeouts auslaufen und stellt vorherige
Vorhaltung wieder her. Wiederherstellungsfehler werden gesondert gemeldet.
Ein Dienstneustart verwendet die gespeicherte normale Konfiguration.

Für den späteren 30-Minuten-Wärmetest: ein vom Benchmarker gewähltes Modell, eine
gewählte Betriebsart, frische IDs, regelmäßiges Keepalive; nach 1800 Sekunden keine
neuen Lastaufträge und explizites Ende. Nachlauf separat ausweisen. Es wurde kein
30-Minuten-Test ausgeführt; Lastschleife und Temperaturverlauf bleiben beim Benchmarker.

## Prüfungen und Review

Alle Code-/HTTP-/FHIR-Tests verwendeten synthetische Daten. Prüfbelege liegen unter
`/private/tmp/kienzledoku18-evidence`; der zusammengefasste Releasebericht wird
unter `github-release/dist/release-1.8-validation.json` dauerhaft abgelegt.

| Prüfung / exakter Befehl | Ergebnis |
| --- | --- |
| `/opt/homebrew/bin/python3.12 installer/run_variant_tests.py client` im Release-Worktree | 314 Tests, 2 zunächst übersprungen; beide Gründe separat geprüft: 5 Packaging-Tests und 1 echter Connect-Prozesstest bestanden |
| `/opt/homebrew/bin/python3.12 -m unittest discover -s tests -p test_commander_benchmark.py -v` | Abschließend 9 Tests, einschließlich zusätzlicher Remote-Herkunft und Ausfall |
| `python3.12 -m unittest discover -s tests -p test_commander_hardware.py` | 5 Hardware-/Timeout-/Null-/WSL-/Unified-Memory-Verträge |
| `python3.12 installer/run_variant_tests.py runtime` | Separate Runtime auf Mac: 136 Tests, 1 Linux-spezifischer Skip |
| `/tmp/kienzledoku18-client-verify/bin/python installer/run_variant_tests.py runtime` im isolierten Linux-Quellstand | 136 Tests auf Linux, kein Skip |
| Linux-Paketprüfung `verify.py` im isolierten Zielverzeichnis | 96 Tests sowie echter VAD-/Connect-/Hersteller-Key-/Manifesttest; 1 plattformbedingter Skip |
| `/usr/local/bin/go test ./...` in `connect` | Bestanden |
| Browser: `tests/ui_status_layout_smoke.cjs`, `ui_installer_smoke.cjs`, `ui_windows_installer_smoke.cjs` | Statuslayout bei 5 Breiten, 3 Skalierungen, 7 Zuständen; beide Assistenten bestanden |
| Neun ausgewählte `server-windows/tests/test_*.ps1` über PowerShell auf Mac | Core, Assistent, Netzwerk, Deinstallation, Updates, Migration, Modelle und Parallelwahl bestanden; Windows-Effekte simuliert |
| `python3.12 installer/runtime_contract.py`, `git diff --check` | Bestanden; 14 gemeinsame Commander-Module und 3 ausdrücklich geprüfte Varianten |

Der portable PowerShell-Updatetest traf zunächst auf den symbolisch verlinkten
macOS-Temppfad. Wiederholung in einem echten `/private/tmp`-Verzeichnis bestand;
die Schutzprüfung im Produkt wurde dafür nicht abgeschwächt.

A07 zusätzlich: je zwei echte frische ASR-/Diar-Umgebungen auf Mac und Linux
installiert, sämtliche Hashes geprüft, `pip check` bestanden, Inventare identisch.
Auf Mac echte Whisper-/Diar-Modellstarts und synthetische Stille mit Metal/MPS
bestanden, pyannote-Metriken nachweislich aus. Linux-CUDA-Verfügbarkeit/Imports
bestanden. Ein zusätzlicher Linux-Modelllauf wurde wegen unzureichend freien VRAMs
vor dem Laden abgebrochen; laufende Modelle wurden nicht gestoppt.

## Pakete, Migration und offene Abnahmen

Reihenfolge eingehalten: Mac-DMG → Linux-Archiv → Windows-Setup/ZIP, alle 1.8.
Mac-Signatur/Nutzlast sowie isolierte Updates 1.7.6→1.8 für Direct und Connect
bestanden, einschließlich Erhalt von VAD-Werten/Tokens/Modellen und Entfernung
alter Programmstände. Linux-Nutzlast nativ geprüft und hashgebunden archiviert.
Windows-Nutzlast wieder entpackt, Quellen/UTF-8/Abhängigkeiten/VC-Bootstrap und
Deinstaller geprüft. Hersteller-Key privat kompiliert, Klartextscans bestanden.
Die laufenden Installationen wurden nicht ersetzt. Keine GitHub-Veröffentlichung.

Noch offen und konkret:

- Windows-Installer vom Benutzer nativ ausführen, einschließlich WSL-Hostdaten,
  Sensorverfügbarkeit, Serverupdate und neuer API.
- Mac-Temperatursensoradapter nur bei später abgestimmter Zusatzkomponente ergänzen;
  die übrige Hardwareanzeige ist vorbereitet.
- Reale Benchmark-Modellwechsel/Parallelbetrieb mit neuer API auf einem dafür
  freigegebenen, freien GPU-Testsystem prüfen. Bisher simulierte Wechseltests,
  keine 30-Minuten-Last und kein Eingriff in laufende Produktivmodelle.
- Später Kienzlebench-UI, vollständig kopierbarer Bericht, UTF-8-Export und
  Temperaturverlauf auf Clientseite implementieren; normaler Interface-Hardware-
  Zusatzstatus ebenfalls separat. Keine weitere Benutzerentscheidung für die
  fertiggestellten 1.8-Installer erforderlich.
