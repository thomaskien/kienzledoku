# Spezifikation Kienzlefon AI CUDA-Serverinstaller

**Version:** 2.0

**Stand:** 25. August 2026

**Referenz:** `install_kienzlefon_ai_server.sh`

## 1. Zweck und Grenze

Der Installer richtet die residenten KI-Grunddienste auf Ubuntu x86_64 mit NVIDIA/CUDA ein. Er verwaltet keine Asterisk-, SIP-, AudioSocket-, VAD-, CallSession-, Patienten-, Dialog- oder medizinische Entscheidungslogik.

| Rolle | Bedeutung | Dienst |
|---|---|---|
| `llm` | Dialogverständnis und strukturierte Antwort | llama.cpp/Qwen3.5-9B, Port 8080 |
| `asr` | Automatic Speech Recognition: Sprache zu Text | Gateway 8178, WhisperLiveKit 8179 |
| `tts` | Text to Speech: Text zu Sprache | Qwen3-TTS, Port 8182 |
| `pyannote` | optionale Sprechertrennung für Dokumentation | Community-1, Port 8183 |
| `all` | LLM, ASR und TTS | Pyannote danach ausdrücklich Ja/Nein |

Piper auf Port 8181 ist ein vorhandener externer Pflicht-Fallback. Der Installer darf Piper weder installieren noch konfigurieren, stoppen, starten, aktualisieren oder deinstallieren. Er führt nur einen Healthcheck aus und warnt bei Nichterreichbarkeit.

## 2. Plattform

- Ubuntu Linux x86_64 und systemd
- normaler Benutzer mit sudo-Berechtigung; kein direkter Root-Start
- funktionierender NVIDIA-Treiber, `nvidia-smi` und vorhandenes CUDA/`nvcc`
- kein macOS-Zweig in der öffentlichen 2.0-Steuerung
- kein CPU-Fallback für eine GPU-Rolle

Treiber und CUDA werden weder installiert noch geändert oder entfernt.

## 3. Rollenwahl und `all`

Ohne `--role` fragt eine interaktive Erstinstallation die Rollen ab. `--role` ist mehrfach möglich. `--role all` wählt:

```text
llm
asr
tts
```

Danach muss Pyannote ausdrücklich bestätigt oder abgelehnt werden. Nichtinteraktiv ist zusammen mit `all` genau eine Option erforderlich:

```text
--with-pyannote
--without-pyannote
```

Eine direkte Auswahl `--role pyannote` gilt als ausdrückliche Zustimmung.

## 4. GPU-Auswahl

Für jede ausgewählte CUDA-Rolle zeigt der Installer Index, NVIDIA-UUID, Modellname und VRAM. Akzeptiert werden Index oder vollständige UUID. Gespeichert wird die UUID in `/etc/kienzlefon-ai/installer-v2.conf`; ein rollenbezogener systemd-Drop-in setzt sie als `CUDA_VISIBLE_DEVICES`.

Nichtinteraktiver Mehr-GPU-Betrieb verwendet:

```text
--llm-gpu INDEX_ODER_UUID
--asr-gpu INDEX_ODER_UUID
--tts-gpu INDEX_ODER_UUID
--pyannote-gpu INDEX_ODER_UUID
```

Eine GPU darf mehreren Rollen zugeordnet werden. Eine gespeicherte UUID muss weiterhin vorhanden sein.

## 5. LLM-Sollstand

| Parameter | Wert |
|---|---|
| Implementierung | llama.cpp |
| Revision | `b9637` |
| Modell | Qwen3.5-9B |
| GGUF | `Qwen_Qwen3.5-9B-Q6_K.gguf` |
| SHA-256 | `073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef` |
| Dateigröße | 7.958.818.848 Byte |
| Port | 8080 |
| Slots | 3 |
| Gesamtkontext | 131072 |
| GPU-Layer | 999 |
| KV-Cache K/V | Q8_0 / Q8_0 |
| Flash Attention | an |
| VRAM-Fit | aus |
| Continuous Batching | an |
| Jinja / mmproj | an / aus |
| Reasoning/Thinking | aus |

Die API ist OpenAI-kompatibel und streamingfähig. Ein technischer LLM-Slot ist nicht automatisch ein freier Telefonplatz.

## 6. ASR-Sollstand

```text
kienzlefon-asr-v1, Port 8178
        │
        ▼
WhisperLiveKit intern, Port 8179
        │
        ▼
Faster-Whisper large-v3 / CUDA
```

Verbindlich sind `simulstreaming`, Sprache `de`, Frame-Threshold 25, Beam 1, Decoder `beam`, `never_fire=false`, PCM-Eingabe, keine Diarisierung und kein CPU-Fallback.

Verboten sind Turbo-ASR, getrennte Live-/Post-ASR, eine zweite Whisper-Instanz für Dokumentation und ein direkter Kienzlefon-Zugriff auf das interne Backend.

Für Kienzledoku wird das residente Backend zusätzlich über den streng
versionsgeprüften Patch `install_final_block_endpoint.sh` um
`POST /v1/asr/final-block` erweitert. Bei einem entfernten Kienzledoku-Client
wird das Backend mit `--asr-backend-bind 0.0.0.0` freigegeben; Port 8179 muss
im geschützten Praxisnetz erreichbar sein. Eine zusätzliche Begrenzung per
Host-Firewall auf die Client-IP ist optional.

## 7. Qwen3-TTS-Sollstand

| Parameter | Wert |
|---|---|
| Modell | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` |
| Quellcommit | `328ab9cb241774572bb59917af199bdf64a17227` |
| Backend | CUDA |
| Quantisierung | INT8 |
| Threads / Batch | 4 / 1 |
| Port | 8182 |
| Sprecher / Sprache | `uncle_fu` / `German` |
| Stream | PCM S16LE, 24000 Hz, mono |

Der systemd-Dienst enthält ausschließlich den CUDA-Aufruf. Ein CUDA-Smoke-Test muss auf der ausgewählten GPU erfolgreich sein; andernfalls bricht die Installation ohne CPU-Fallback ab.

Bekannte alte Qwen-Drop-ins für INT4 oder Batch 2 werden beim 2.0-Upgrade gezielt entfernt, damit sie den Sollstand nicht übersteuern. Der GPU-Drop-in bleibt erhalten.

## 8. Pyannote-Sollstand

Pyannote ist ein eigenständiger optionaler Dokumentationsdienst:

- `pyannote/speaker-diarization-community-1`
- `torch==2.11.0`, `torchaudio==2.11.0`, CUDA-Wheels
- `pyannote.audio>=4.0,<5`
- Port 8183 und kein CPU-Fallback
- maximal 100 MiB Eingabe je Request
- `GET /health` und `POST /v1/diarize`

Innerhalb der durch UUID begrenzten Prozesssicht verwendet der Dienst `cuda:0`. Er liefert neutrale Sprecherkennungen; die Rollenfestlegung erfolgt nachgelagert.

## 9. Tokenbehandlung

Der Installer erläutert Konto, Modellfreigabe, persönlichen Read-Token und die verdeckte Eingabe beziehungsweise Übergabe über den Pfad einer Modus-0600-Datei.

Nicht zulässig sind Tokenwert als Klartext-CLI-Argument, Token in `installer-v2.conf`, allgemeiner TOML, Dokumentation oder Logs sowie Konsolenausgabe des Werts.

Ein installierter Token liegt ausschließlich in
`/etc/kienzlefon-ai/diarization.env`, Eigentümer root, Modus 0600. Siehe
[`PYANNOTE-HUGGINGFACE-TOKEN.md`](PYANNOTE-HUGGINGFACE-TOKEN.md).

## 10. Aktionen und Pfade

Aktionen: `install`, `configure`, `start`, `stop`, `restart`, `status`, `test`, `uninstall`. Ohne Rollenwahl verwenden Managementaktionen den gespeicherten Zustand. Ein Uninstall entfernt nur die ausgewählten Rollen; Piper, Asterisk, NVIDIA-Treiber und CUDA bleiben unangetastet.

Gespeicherte Bind-Adresse, Sonderports und GPU-UUIDs werden bei späteren Managementaktionen wieder geladen; eine ausdrücklich angegebene Kommandozeilenoption hat Vorrang. `configure` schreibt bei Qwen und Pyannote die verwaltete Laufzeitkonfiguration einschließlich Port beziehungsweise Bind-Adresse neu. Beim Rollen-Uninstall werden auch die zu dieser Rolle gehörenden 2.0-systemd-Drop-ins entfernt.

LLM/ASR/Pyannote verwenden:

```text
/opt/kienzlefon-ai-v2
/etc/kienzlefon-ai/kienzlefon-ai-v2.toml
/etc/kienzlefon-ai/versions-v2.conf
/etc/kienzlefon-ai/installer-v2.conf
/var/log/kienzlefon-ai-v2
```

Qwen3-TTS behält seine eigenständigen Pfade unter `/opt/kienzlefon/qwen3-tts` und `/etc/kienzlefon/qwen3-tts.env`.

## 11. Prüfgrenzen

Statisch: Shellsyntax, eingebettete Payloads, Python-Syntax, `--version`, `--help`, `--self-test` sowie Modell-, Hash-, Parameter-, GPU-, Token- und Piper-Vertrag.

Gesondert freigabepflichtig: APT/Pip/Git-Downloads, Builds, Dienstinstallation, echte GPU-Zuordnung/VRAM, Modell-/Audio-End-to-End-Test und Uninstall.
