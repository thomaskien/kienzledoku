# Herkunft und Referenzstände

Kienzledoku 1.2 wurde aus den lokal übergebenen, überprüften Referenzständen
zusammengeführt. Die Archive und ihre entpackten Referenzen außerhalb dieses
Verzeichnisses bleiben unverändert.

| Referenz | SHA-256 / Stand |
| --- | --- |
| `whisperdoku-t2med-macos-v0.1.2.zip` | `769bd4cfb5d4281a72ee6a0c267cc5f1f10d4e22e729b3bb57b82c0c129babd2` |
| T2med-Quellskript v0.1.2 | `d1507f91e62674430b845e568acf92c9cc195d00b60b545208b20e3430990666` |
| T2med-Installer v0.1.2 | `afbae93a76d290a47a167cfd203a140e2abb738932a7ef8e347b36c4f2040184` |
| `kienzlefon-whisperdoku-v6.2-final-block-macos-universal.zip` | `f5a1024007a0c84ce098ff594d4d50f8b439b14c32218da1209e8bd47af02089` |
| Offizielle T2med-Demoanwendung, geprüfter Commit | `82bcaf8d25b1fc438db56d92938448a4502c5519` |

Die alte Bezeichnung WhisperDoku erscheint nur dort, wo Herkunft oder
Rückwärtskompatibilität dokumentiert werden muss. Neue Produkttexte,
Schlüsselbundnamen, Installationspfade und das kanonische URL-Schema verwenden
Kienzledoku.

## Kienzledoku Local AI 1.0

Der mitgelieferte macOS-Installer verwendet festgeschriebene Referenzen:

| Komponente | Referenz |
| --- | --- |
| llama.cpp | Commit `aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3`, Build `b9637` |
| Qwen3.5-9B Q6_K | Revision `2dcd842c59ea5eb119267064550a7a4c592b16c3`, SHA-256 `073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef` |
| Whisper large-v3 MLX | Revision `49e6aa286ad60c14352c404340ded53710378a11`, Gewichte SHA-256 `05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d` |
| pyannote Community-1 | Revision `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee` |

Die vollständigen Versionswerte und Selbstprüfungen liegen in
[`local-ai-macos/manager_macos.sh`](local-ai-macos/manager_macos.sh).

## Linux/NVIDIA-Server 2.0

Der Ubuntu-Serverinstaller wurde aus dem lokal geprüften Kienzlefon-AI-Stand
2.0 übernommen und um die explizite Netzwerkbindung des residenten
Final-Block-ASR-Backends für einen entfernten Kienzledoku-Client ergänzt.

| Bestandteil | SHA-256 / Referenz |
| --- | --- |
| `server-linux/install_kienzlefon_ai_server.sh` | `e0acae2d013f57b827fad172eef6349d63a5d98540f7fb27161b2a6045a83f63` |
| `server-linux/install_final_block_endpoint.sh` | `c38e5c8a865c230b6f7966d5ff66a895bd07eea7bd0e9c28e0fea26ae64e995d` |
| WhisperLiveKit | Version `0.2.24` |
| erwartete unveränderte `basic_server.py` | `ae89062f8f7146a130e48b973187cd81f6451a672d93bc04e9ec1fcbb28fe78f` |

Der Final-Block-Installer verändert nur exakt diesen geprüften
WhisperLiveKit-Ausgangsstand. Bei einer abweichenden Prüfsumme bricht er vor
jeder Änderung ab. Vor dem Patch wird ein Root-Backup angelegt; ein fehlerhafter
Syntax-, Dienst- oder Healthcheck löst automatisch die Wiederherstellung aus.
