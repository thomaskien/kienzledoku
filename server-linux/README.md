# Kienzledoku-KI-Dienste auf Ubuntu/NVIDIA

Dieser Ordner enthält die Linux-Serverinstallation für einen Kienzledoku-Client
auf einem anderen Rechner. Die Dienste laufen resident unter systemd:

> [!TIP]
> **Diese dedizierte Serverinstallation ist die empfohlene
> Kienzledoku-Betriebsvariante.** Der T2med-Mac bleibt dabei der schlanke
> Client, während Modellbetrieb, GPU-Last und Wartung der KI-Dienste auf dem
> Ubuntu-/NVIDIA-Server gebündelt werden. Die Dienste gehören ausschließlich
> ins geschützte Praxisnetz und müssen per Firewall auf die vorgesehenen
> Clients begrenzt werden.

| Dienst | Implementierung | Port für Kienzledoku |
| --- | --- | --- |
| LLM | Qwen3.5-9B Q6_K über llama.cpp/CUDA | `8080` |
| Final-Block-ASR | Whisper large-v3 über WhisperLiveKit/Faster-Whisper | `8179` |
| Diarisierung | pyannote Community-1/CUDA | `8183` |

Der allgemeine Kienzlefon-ASR-Gateway auf Port `8178` wird mitinstalliert,
Kienzledoku verwendet für abgeschlossene Sprachblöcke aber direkt
`POST /v1/asr/final-block` auf Port `8179`. TTS wird für Kienzledoku nicht
benötigt und vom Kienzledoku-Gesamtinstaller nicht ausgewählt.

> [!IMPORTANT]
> Die Installation ist ausschließlich für Ubuntu 24.04 x86_64 mit
> NVIDIA-GPU, systemd und CUDA vorgesehen. Sie verändert Pakete, Python-
> Umgebungen und systemd-Dienste und lädt mehrere Gigabyte Modelle. Vorher ein
> Serverbackup erstellen und nicht auf einem ungeprüften Produktivsystem
> ausführen.

## Voraussetzungen

- Ubuntu 24.04 LTS, x86_64;
- normaler Benutzer mit `sudo`-Berechtigung, kein direkter Root-Start;
- NVIDIA-GPU mit ausreichend VRAM;
- funktionierender NVIDIA-Treiber, `nvidia-smi`, CUDA und `nvcc`;
- Internetzugriff für APT, Pip, Git und Modelldownloads;
- für pyannote ein Hugging-Face-Read-Token und akzeptierte Bedingungen für
  `pyannote/speaker-diarization-community-1`.

Auf einem frischen Host kann zunächst die mitgelieferte Hostvorbereitung
verwendet werden:

```bash
./prepare_ubuntu_24_04_nvidia.sh
```

Wenn dabei ein NVIDIA-Treiber neu installiert wird, ist vor dem nächsten
Schritt ein Neustart erforderlich.

## Vollständige Installation für Kienzledoku

Auf dem Linux-Server:

```bash
chmod +x *.sh
./install_kienzledoku_servers.sh --bind SERVER_LAN_IP
```

`SERVER_LAN_IP` ist die feste IP-Adresse des Linux-Servers im Praxisnetz,
beispielsweise `10.0.83.140`. Der Installer fragt interaktiv nach der
GPU-Zuordnung und dem Hugging-Face-Token. Er installiert LLM, ASR und
Diarisierung, aktiviert den Final-Block-Endpunkt und lässt die Modelle resident
laufen.

Der interne WhisperLiveKit-Port `8179` wird für den entfernten Kienzledoku-Mac
an `0.0.0.0` gebunden. Deshalb muss die Firewall diesen Port sowie `8080` und
`8183` ausschließlich für die IP des Kienzledoku-Macs freigeben. Beispiel mit
aktivem UFW:

```bash
sudo ufw allow from KIENZLEDOKU_MAC_IP to any port 8080 proto tcp
sudo ufw allow from KIENZLEDOKU_MAC_IP to any port 8179 proto tcp
sudo ufw allow from KIENZLEDOKU_MAC_IP to any port 8183 proto tcp
```

Keine dieser APIs direkt aus dem Internet erreichbar machen. LLM und
Diarisierung besitzen keine eigene Authentifizierung. Auch ein ASR-Token
ersetzt keine Netzwerksegmentierung.

## Einzelne Server installieren

Die Rollen können einzeln und additiv installiert werden:

```bash
./install_llm_server.sh --bind SERVER_LAN_IP
./install_asr_server.sh --bind SERVER_LAN_IP
./install_diarization_server.sh --bind SERVER_LAN_IP
```

Der ASR-Installer führt nach WhisperLiveKit automatisch den streng
versionsgeprüften Final-Block-Patch aus. Der Patch akzeptiert ausschließlich
WhisperLiveKit `0.2.24` mit der erwarteten SHA-256 der analysierten
`basic_server.py`; bei einer Abweichung bricht er ab, ohne die Datei zu ändern.

Eine nichtinteraktive Installation benötigt stabile GPU-Zuordnungen. Für
pyannote wird der Token ausschließlich über den Pfad einer geschützten Datei
übergeben:

```bash
chmod 600 /geschuetzter/pfad/hf-token.txt
./install_kienzledoku_servers.sh \
  --bind SERVER_LAN_IP \
  --llm-gpu 0 \
  --asr-gpu 0 \
  --pyannote-gpu 0 \
  --hf-token-file /geschuetzter/pfad/hf-token.txt \
  --non-interactive
```

## Kienzledoku auf dem Mac konfigurieren

Im macOS-App-Installer für alle drei Dienste die IP des Linux-Servers
eintragen:

| Abfrage | Host | Port |
| --- | --- | --- |
| ASR | `SERVER_LAN_IP` | `8179` |
| Diarisierung | `SERVER_LAN_IP` | `8183` |
| LLM | `SERVER_LAN_IP` | `8080` |

## Status und Tests

Auf dem Linux-Server:

```bash
./status_linux_services.sh
./test_linux_services.sh
```

Den Final-Block-Endpunkt von einem Client mit einer synthetischen oder
freigegebenen WAV-Datei prüfen:

```bash
./test_final_block_endpoint.sh SERVER_LAN_IP test.wav de
```

Falls WhisperLiveKit mit einem Bearer-Token geschützt ist, diesen nur für den
Testprozess setzen:

```bash
export WLK_API_TOKEN='...'
./test_final_block_endpoint.sh SERVER_LAN_IP test.wav de
unset WLK_API_TOKEN
```

## Rollback des Final-Block-Patches

Der Patch legt vor jeder Änderung ein Root-Backup der realen
`basic_server.py` an. Nur den Final-Block-Patch zurückrollen:

```bash
sudo ./rollback_final_block_endpoint.sh
```

Management und rollenbezogene Deinstallation erfolgen über den Hauptinstaller:

```bash
./install_kienzlefon_ai_server.sh --action stop
./install_kienzlefon_ai_server.sh --action restart
./install_kienzlefon_ai_server.sh --action uninstall --role pyannote
```

## Technische Dokumentation

- [`SERVER-INSTALLER-SPEC.md`](SERVER-INSTALLER-SPEC.md) – Rollen,
  Modellstände, GPU-Zuordnung und Pfade
- [`PYANNOTE-HUGGINGFACE-TOKEN.md`](PYANNOTE-HUGGINGFACE-TOKEN.md) – sichere
  Tokenübergabe und Rotation
