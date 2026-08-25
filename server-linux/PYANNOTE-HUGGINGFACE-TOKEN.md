# Pyannote / Hugging Face – Tokenanleitung für Installer 2.0

## Wofür der Token benötigt wird

Die optionale Rolle `pyannote` lädt beim ersten Start das Modell:

`pyannote/speaker-diarization-community-1`

Dafür sind ein Hugging-Face-Konto, die Annahme der Modellbedingungen und ein persönlicher Read-Token erforderlich. LLM, ASR und TTS benötigen diesen Token nicht.

## Token erzeugen

1. Auf [Hugging Face](https://huggingface.co/) registrieren oder anmelden.
2. Die Seite [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) öffnen.
3. Die dort angezeigten Nutzungsbedingungen beziehungsweise Zugriffsbedingungen akzeptieren.
4. In den Kontoeinstellungen `Settings` → `Access Tokens` öffnen.
5. Einen neuen persönlichen Token mit ausschließlich lesendem Zugriff (`Read`) erzeugen.
6. Den Token nur in einem Passwortmanager oder einer geschützten lokalen Datei aufbewahren.

Ein Read-Token reicht für den Modelldownload. Kein Schreib- oder Administrationsrecht vergeben.

## Sichere Übergabe

### Interaktiv

```bash
./install_diarization_server.sh --bind SERVER_LAN_IP
```

Der Installer fragt den Token verdeckt ab. Die eingegebenen Zeichen werden nicht angezeigt.

### Nichtinteraktiv über einen Dateipfad

Token in eine ausschließlich für den Besitzer lesbare Datei legen:

```bash
chmod 600 /geschuetzter/pfad/hf-token.txt
./install_diarization_server.sh \
  --bind SERVER_LAN_IP \
  --pyannote-gpu 0 \
  --hf-token-file /geschuetzter/pfad/hf-token.txt \
  --non-interactive
```

Die Option enthält nur den Dateipfad, niemals den Tokenwert. Die Datei soll genau den Token in der ersten Zeile enthalten.

## Speicherung auf dem Server

Der Installer speichert den Token ausschließlich hier:

```text
/etc/kienzlefon-ai/diarization.env
```

Verbindliche Rechte:

```text
Eigentümer: root
Gruppe:     root
Modus:      0600
```

Nicht gespeichert wird der Token in:

- `/etc/kienzlefon-ai/installer-v2.conf`
- `/etc/kienzlefon-ai/kienzlefon-ai-v2.toml`
- normalen Dienstlogs
- Benchmarkdateien
- Projekt- oder Markdowndateien
- einem Klartext-CLI-Argument

## Prüfung ohne Tokenausgabe

Dateirechte prüfen:

```bash
sudo stat -c '%U %G %a %n' /etc/kienzlefon-ai/diarization.env
```

Erwartet wird:

```text
root root 600 /etc/kienzlefon-ai/diarization.env
```

Dienst und Health-Endpunkt prüfen, ohne die Umgebungsdatei auszugeben:

```bash
systemctl --no-pager --full status kienzlefon-ai-diarization.service
curl -fsS http://127.0.0.1:8183/health
```

Den Inhalt der Umgebungsdatei nicht mit `cat`, `grep`, Shell-Debugging oder in Supportausgaben anzeigen.

## Rotation und Widerruf

Bei Verdacht auf Offenlegung:

1. Token sofort in den Hugging-Face-Kontoeinstellungen widerrufen.
2. Neuen Read-Token erzeugen.
3. Pyannote mit verdeckter Eingabe oder neuer geschützter Token-Datei erneut konfigurieren/installieren.
4. Prüfen, ob alte Shellverläufe, Supportausgaben, Snapshots, Backups oder Repositorys den Token enthalten.
5. Betroffene Kopien nach gesonderter Freigabe bereinigen.

Ein Token darf nie durch bloßes Löschen einer lokalen Datei als sicher gelten; maßgeblich ist der Widerruf beim Anbieter.

## Repository-Grenze

Dieses Repository enthält keine `diarization.env` und keinen Tokenwert. Solche
Laufzeitdateien oder Systemsnapshots dürfen nicht in Git, Release-Archive oder
Supportanhänge aufgenommen werden.
