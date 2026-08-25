# Kienzledoku Local AI 1.0 für Apple Silicon

Dieser eigenständige Installer bringt die von Kienzledoku verwendeten
Modelldienste wahlweise einzeln oder kombiniert lokal auf einen Mac mini M4
mit 32 GB. Er verändert den
Kienzlefon-AI-Installer und dessen Server-Snapshot nicht.

## Exakter Modell- und Schnittstellenstand

| Dienst | Lokaler Modellstand | Beschleunigung | kompatible Schnittstelle |
| --- | --- | --- | --- |
| LLM | `Qwen_Qwen3.5-9B-Q6_K.gguf`, SHA-256 `073a9275…bfef` | llama.cpp `b9637`, Metal, vollständiges GPU-Offloading | OpenAI-kompatibel, Port 8080, Alias `qwen3.5-9b` |
| ASR | `mlx-community/whisper-large-v3-mlx` @ `49e6aa2…` | MLX/Metal | `POST /v1/asr/final-block`, Port 8179 |
| Diarisierung | `pyannote/speaker-diarization-community-1` @ `3533c8c…` | PyTorch MPS | `POST /v1/diarize`, Port 8183 |

Das LLM verwendet auf dem 32-GB-Mac ein dokumentationsgerechtes Ein-Slot-Profil
mit insgesamt 32.768 Token Kontext und F16-KV-Cache. Modell, Alias,
Thinking-Einstellung und HTTP-Vertrag sind identisch mit dem produktiven
Kienzlefon-Stand; das große Drei-Slot-CUDA-Speicherprofil wird nicht auf den
32-GB-Mac übertragen. Der Start erzwingt das erkannte Apple-Metal-Gerät
`MTL0`; ein stiller reiner CPU-Betrieb ist dadurch ausgeschlossen.

Whisper wird beim Dienststart über den internen `ModelHolder` von
`mlx-whisper` einmal geladen und danach prozessweit wiederverwendet. Auch Qwen
und pyannote bleiben resident, bis die Dienste gestoppt oder der Benutzer
abgemeldet wird. Die Whisper-Anfragen werden bewusst seriell im selben Thread
wie der MLX-GPU-Stream verarbeitet; Kienzledoku reiht Finalblöcke bereits in
dieser Reihenfolge ein.

## Voraussetzungen

- Mac mit Apple Silicon, native `arm64`; Zielprofil: Mac mini M4, 32 GB
- je nach Auswahl etwa 7 bis 25 GiB freier Speicher
- Xcode Command Line Tools (`xcode-select --install`)
- natives Homebrew unter `/opt/homebrew`
- nur bei Auswahl von pyannote: Hugging-Face-Konto mit akzeptierten Bedingungen für
  [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
- Hugging-Face-Lesetoken aus den [Token-Einstellungen](https://huggingface.co/settings/tokens)

Der Token wird während der Installation verdeckt abgefragt, nur an den
einmaligen, fest revisionierten Download übergeben und nicht gespeichert.

## Installation

Im Hauptverzeichnis des Repositorys doppelklicken oder im Terminal ausführen:

```bash
./install_local_ai_macos.command
```

Der Installer fragt zuerst nach den Komponenten. Möglich sind `LLM`,
`Whisper` und `pyannote` einzeln sowie jede beliebige Kombination. Nur die
gewählten Modelle, Python-Umgebungen und Build-Abhängigkeiten werden neu
installiert. Bei einer erneuten Installation bleiben bereits vorhandene, aber
nicht mehr gewählte Modelldateien vorsichtshalber gespeichert; ihre Dienste
werden jedoch deaktiviert.

### Einzelne Server additiv nachinstallieren

Die folgenden Einstiegspunkte liegen im Hauptverzeichnis des Repositorys. Sie
installieren genau den genannten Server und erhalten bereits aktivierte
Komponenten:

```bash
./install_llm_server_macos.command
./install_asr_server_macos.command
./install_diarization_server_macos.command
```

Intern verwenden sie `--add-components llm`, `whisper` beziehungsweise
`pyannote`. Ein vorhandener Startmodus bleibt erhalten. Beim ersten
Serverinstaller werden Listen-Adresse und Startmodus normal abgefragt.

Danach fragt der Installer nach der IPv4-Listen-Adresse:

- `127.0.0.1` ist der sichere Standard und erlaubt nur Zugriffe von diesem Mac.
- `0.0.0.0` bedeutet **alle IPs beziehungsweise Netzwerkschnittstellen** des
  Macs. Die APIs werden dadurch grundsätzlich für andere Geräte im erreichbaren
  Netzwerk sichtbar. Da sie keine Anmeldung besitzen, verlangt der Installer
  hierfür eine zusätzliche Bestätigung.
- Eine konkrete andere IPv4-Adresse bindet nur an die zugehörige Schnittstelle.

Wenn `0.0.0.0` gewählt wurde, verbindet sich Kienzledoku auf demselben Mac
trotzdem korrekt über `127.0.0.1`; `0.0.0.0` ist eine Listen-, keine sinnvolle
Zieladresse.

Anschließend wird der Startmodus abgefragt:

1. `autostart`: ausgewählte Modelle bei jeder macOS-Anmeldung laden und jetzt starten;
2. `manual`: ausgewählte Modelle nur jetzt laden und später bei Bedarf über
   `start_once_macos.command` erneut starten.

Für einen nicht interaktiven Aufruf:

```bash
./install_local_ai_macos.command \
  --components all --listen-address 127.0.0.1 --mode autostart

./install_local_ai_macos.command \
  --components whisper --listen-address 127.0.0.1 --mode manual

./install_local_ai_macos.command \
  --components llm,pyannote --listen-address 0.0.0.0 --mode manual

./install_diarization_server_macos.command \
  --listen-address 127.0.0.1 --mode autostart
```

Die Installation liegt vollständig unter:

```text
~/Library/Application Support/Kienzledoku Local AI
```

Ist ein kompatibler lokaler Kienzlefon-Snapshot neben dem Repository vorhanden,
wird seine Q6_K-Datei nach Größen- und SHA-256-Prüfung wiederverwendet. Sonst
lädt der Installer dieselbe festgeschriebene Hugging-Face-Revision. Whisper wird
ebenfalls mit festen Dateiprüfsummen installiert. Ein abweichender lokaler
Q6_K-Pfad kann über `KIENZLEDOKU_Q6_SOURCE` angegeben werden.

## Manuelles Laden, Stoppen und Prüfen

Die Finder-kompatiblen Skripte in diesem Verzeichnis sind:

```text
start_once_macos.command
stop_macos.command
status_macos.command
```

Alternativ im Terminal:

```bash
"$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh" --action start
"$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh" --action stop
"$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh" --action status
"$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh" --action test
```

`--action status` prüft die schnellen Health-Endpunkte. `--action test` sendet
zusätzlich eine künstliche einsekündige WAV-Datei an Whisper und prüft damit
auch die echte MLX/Metal-Inferenz; es werden dabei keine Mikrofon- oder
Patientendaten verwendet.

Start und Autostart setzen nur für die ausgewählten Komponenten die passenden
`KIENZLEDOKU_*_URL`-Variablen über `launchctl`. Nicht ausgewählte lokale
Endpunkte werden nicht eingetragen. Das gilt für danach gestartete
Kienzledoku-Prozesse.
War Kienzledoku während der Installation bereits offen, die App einmal beenden
und erneut aus T2med öffnen.

Mit der empfohlenen Vorgabe sind die Dienste nur an Loopback gebunden. Bei
`0.0.0.0` oder einer LAN-Adresse muss der Netzwerkzugriff bewusst abgesichert
werden; die Schnittstellen selbst haben keine Authentifizierung. Audio,
Transkripte und LLM-Eingaben werden nicht in den Dienstlogs gespeichert.

## Deinstallation

Im Hauptverzeichnis:

```bash
./uninstall_local_ai_macos.command
```

Entfernt werden alle zu diesem Paket gehörenden LaunchAgents, die installierten Runtimes, Modelle,
Quellen und technischen Logs dieses Installers. Nicht entfernt werden die
Kienzledoku-App, Kienzlefon-Snapshots, Homebrew oder Homebrew-Pakete.

## Wichtiger MPS-Hinweis zu pyannote

Whisper/MLX und llama.cpp/Metal sind die nativen Apple-Silicon-Pfade. Pyannote
selbst dokumentiert offiziell vor allem CUDA-GPU-Betrieb; MPS läuft über den
Apple-Backendpfad von PyTorch. Für einzelne PyTorch-/macOS-Versionen sind
upstream MPS-Probleme gemeldet worden. Dieser Dienst prüft MPS beim Start und
deaktiviert `PYTORCH_ENABLE_MPS_FALLBACK`; er täuscht daher niemals einen
beschleunigten Betrieb durch stilles Ausweichen auf die CPU vor. Ein echter
Mikrofon-/Diarisierungs-End-to-End-Test auf dem Ziel-M4 bleibt nach der
Installation erforderlich.

Technische Referenzen:

- [MLX Whisper (Apple)](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
- [pyannote.audio](https://github.com/pyannote/pyannote-audio)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
