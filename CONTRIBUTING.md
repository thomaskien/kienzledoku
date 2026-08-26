# Zu Kienzledoku beitragen

Vielen Dank für das Interesse an Kienzledoku. Änderungen sollten klein,
nachvollziehbar und ohne echte medizinische oder personenbezogene Daten
eingereicht werden.

## Vor einem Issue

- Prüfen, ob das Verhalten bereits in der README oder in einem bestehenden
  Issue beschrieben ist.
- Version, Betriebssystem-/Desktop-Version, Python-Version und die betroffene
  Komponente nennen.
- Nur synthetische Patientendaten und bereinigte Protokollauszüge verwenden.
- Sicherheitsprobleme gemäß [`SECURITY.md`](SECURITY.md) vertraulich melden.

## Lokale Entwicklung

Voraussetzung ist Python 3.9 oder neuer. Für den netzwerkfreien Testlauf sind
keine installierten Kienzlefon- oder T2med-Dienste erforderlich:

```bash
python3 -m unittest discover -s tests -v
python3 kienzledoku.py --self-test
./local-ai-macos/manager_macos.sh --action self-test
./install_linux.sh --self-test
./server-linux/install_kienzlefon_ai_server.sh --self-test
```

Der native macOS-WebKit-Container kann mit installierten Xcode Command Line
Tools neu gebaut werden:

```bash
./build_native_window_macos.sh
```

Der Build erzeugt das Universal-Binary `kienzledoku_window` für Intel- und
Apple-Silicon-Macs und signiert es lokal ad hoc.

Unter Ubuntu 24.04 wird der GTK-4-/WebKitGTK-6.0-Container aus dem enthaltenen
C-Quelltext gebaut:

```bash
./build_native_window_linux.sh
```

Der produktive Installer legt diesen Helfer root-eigen unter `/usr/local`
ab. Änderungen an `linux/kienzledoku.apparmor` dürfen die WebKit-Sandbox oder
Ubuntus systemweite User-Namespace-Beschränkung nicht deaktivieren.

## Anforderungen an Änderungen

- Patientendaten, Tokens, API-Schlüssel, Zertifikate, Audiodateien und
  unbereinigte Transkripte dürfen nie committed werden.
- Der Vier-Felder-Vertrag `anamnese`, `befund`, `therapie`, `prozedere` darf
  nicht stillschweigend erweitert oder aufgeweicht werden.
- Die T2med-Übernahme muss atomar bleiben; Teilerfolge gelten nicht als
  erfolgreiche Dokumentation.
- Deep Links, OAuth-Token und Dokumentationsinhalte dürfen nicht protokolliert
  werden.
- Netzwerkziele dürfen nicht ohne explizite Validierung erweitert werden.
- Änderungen an Modellrevisionen, Dateigrößen oder Prüfsummen des
  Local-AI-Installers müssen begründet und separat geprüft werden.
- Der Linux-Final-Block-Patch darf unbekannte WhisperLiveKit-Ausgangsdateien
  niemals verändern; die SHA-256-Schranke und der automatische Rollback müssen
  erhalten bleiben.
- Neue oder geänderte Funktionen benötigen passende Tests.
- Benutzertexte und Dokumentation werden auf Deutsch gepflegt.

## Pull Requests

Ein Pull Request sollte enthalten:

- eine kurze Beschreibung von Problem und Lösung;
- die durchgeführten automatischen und manuellen Tests;
- Hinweise auf Datenschutz- oder Sicherheitsauswirkungen;
- bei UI-Änderungen einen Screenshot mit ausschließlich synthetischen Daten;
- bei Änderungen an FHIR, ASR, Diarisierung oder LLM die verwendeten
  Testdoubles beziehungsweise kontrollierten Testdienste.

Vor dem Einreichen sollten beide lokalen Testbefehle erfolgreich sein. Ein
echter T2med- oder Mikrofontest ist nur nötig, wenn die Änderung diesen Bereich
berührt, muss dann aber im Pull Request dokumentiert werden.
