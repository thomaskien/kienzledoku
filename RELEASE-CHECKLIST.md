# Checkliste für die GitHub-Veröffentlichung

Diese Checkliste gilt für die saubere Repository-Wurzel. README, App-Installer
und Local-AI-Installer liegen direkt beziehungsweise im Ordner
`local-ai-macos`; ein zusätzliches Versionsverzeichnis ist nicht vorgesehen.
Ein übergeordnetes Entwicklungsverzeichnis mit Archiven, Testaufnahmen,
virtuellen Umgebungen oder lokalen Zugangsdaten darf nicht veröffentlicht
werden.

## Vor dem ersten öffentlichen Push

- [ ] Nur den Inhalt der sauberen Repository-Wurzel veröffentlichen.
- [ ] Eine Lizenz auswählen und als `LICENSE` hinzufügen.
- [ ] Repository-URL und verantwortlichen Kontakt festlegen.
- [ ] Private Schwachstellenmeldungen in GitHub unter `Security` aktivieren.
- [ ] Sicherstellen, dass keine WAV-/Audio-, Transkript-, Token-, Schlüssel-,
  Zertifikats-, Konfigurations- oder Logdateien erfasst werden.
- [ ] Screenshots nochmals auf Patienten-, Praxis- und Zugangsdaten prüfen.
- [ ] Prüfen, dass alle Versionsangaben in Python, Installer, nativem Fenster
  und Dokumentation auf `1.2` stehen.
- [ ] Netzwerkfreie Tests ausführen.
- [ ] Modellfreien Selbsttest des Local-AI-Installers ausführen.
- [ ] Statischen Selbsttest des Ubuntu/NVIDIA-Installers ausführen.
- [ ] Prüfen, dass Local-AI-Modellrevisionen und Prüfsummen unverändert sind.
- [ ] Native Intel- und Apple-Silicon-Binärdatei prüfen.
- [ ] Realen Integrationstest mit synthetischem T2med-Testpatienten,
  Mikrofon, ASR, Diarisierung und LLM dokumentieren.
- [ ] Bekannte TLS- und Host-Beschränkungen in Release Notes und README
  sichtbar lassen.
- [ ] Entscheiden, ob Binär-Releases signiert und notarisiert werden sollen.

## Prüfkommandos

```bash
python3 -m unittest discover -s tests -v
python3 kienzledoku.py --self-test
python3 -m py_compile \
  kienzledoku.py \
  kienzledoku_document.py \
  kienzledoku_speech.py \
  kienzledoku_asr_v6.py
bash -n \
  install_all_macos.command \
  install_local_ai_macos.command \
  install_llm_server_macos.command \
  install_asr_server_macos.command \
  install_diarization_server_macos.command \
  uninstall_local_ai_macos.command \
  install_macos.command \
  uninstall_macos.command \
  set_api_key_macos.command \
  use_demo_key_macos.command \
  start_kienzledoku_asr.sh \
  build_native_window_macos.sh \
  local-ai-macos/manager_macos.sh \
  local-ai-macos/start_once_macos.command \
  local-ai-macos/stop_macos.command \
  local-ai-macos/status_macos.command \
  server-linux/prepare_ubuntu_24_04_nvidia.sh \
  server-linux/install_kienzlefon_ai_server.sh \
  server-linux/install_kienzledoku_servers.sh \
  server-linux/install_llm_server.sh \
  server-linux/install_asr_server.sh \
  server-linux/install_diarization_server.sh \
  server-linux/install_final_block_endpoint.sh \
  server-linux/rollback_final_block_endpoint.sh \
  server-linux/test_final_block_endpoint.sh \
  server-linux/status_linux_services.sh \
  server-linux/test_linux_services.sh
./local-ai-macos/manager_macos.sh --action self-test
./server-linux/install_kienzlefon_ai_server.sh --self-test
```

Nach der Git-Initialisierung zusätzlich:

```bash
git status --short
git ls-files
git grep -nEi '(token|secret|password|oauth|api.key)'
```

Der letzte Befehl liefert auch beabsichtigte Treffer in Quellcode und
Dokumentation. Jeder Treffer muss einzeln geprüft werden; Schlüsselwerte oder
reale Tokens dürfen nicht enthalten sein.

## Empfohlene Release-Angaben

- Tag: `v1.2.0`
- Titel: `Kienzledoku 1.2`
- Plattform: Kienzledoku-App für Intel und Apple Silicon; Local AI für Apple
  Silicon mit mindestens 32 GB Unified Memory; Serverdienste für Ubuntu 24.04
  x86_64 mit NVIDIA/CUDA
- Status: Entwicklungs- und Integrationsstand
- Verweis auf `CHANGELOG.md`, `SECURITY.md` und die Sicherheitsgrenzen der
  README
