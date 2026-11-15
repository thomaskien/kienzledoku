# Installation

[Zur Übersicht](../README.md) · [T2med einrichten](../README.md#t2med-einrichten-und-verwenden)

Diese Anleitung beschreibt die gemeinsame Installer-Ausgabe **1.7.6** für Windows,
macOS und Linux. [Pakete und Quellcode](https://github.com/thomaskien/kienzledoku/releases/tag/v1.7.6)
sind veröffentlicht. Ein Quellcode-ZIP ist kein Ersatz für die fertigen Installer
mit eingebetteten Laufzeiten.

[Veröffentlichte Installer auf GitHub](https://github.com/thomaskien/kienzledoku/releases)

Wählen Sie **Client**, **Server** oder **beides**. Für den Client werden Mikrofon,
T2med-Verbindung und die Adresse des Commanders benötigt. Ein vorhandener
KI-Server kann von mehreren Arbeitsplätzen im Praxisnetz verwendet werden.

## Hugging-Face-Token einrichten

Der KI-Server benötigt für den Download geschützter Modelle einen Hugging-Face-Zugang,
insbesondere für die **Sprechertrennung mit pyannote Community-1**. Ein reiner Client
an einem bereits eingerichteten Server benötigt dafür keinen eigenen Token.

1. Bei [Hugging Face](https://huggingface.co/join) ein Konto erstellen oder anmelden.
2. Die [Modellseite von pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) öffnen, die angezeigten Bedingungen lesen und akzeptieren. Die abgefragten Angaben ausfüllen und die Zugriffsfreigabe abwarten. **Token und Modellfreigabe müssen zum selben Konto gehören.**
3. Unter [Settings → Access Tokens](https://huggingface.co/settings/tokens) auf **New token** klicken. Als Namen beispielsweise `KienzleDoku` und als Typ **Read** wählen. Schreibrechte sind für den Download nicht erforderlich. Alternativ ist ein **Fine-grained**-Token mit Lesezugriff auf die benötigten, freigeschalteten Modell-Repositories möglich. [Token-Typen bei Hugging Face](https://huggingface.co/docs/hub/security-tokens).
4. Den erzeugten Token kopieren; er beginnt mit `hf_`. Im grafischen Installer unter **Sprache → Hugging-Face-Token** einfügen und die Installation fortsetzen. Der Linux-Installer fragt nach dem **Hugging-Face-Read-Token**: Die Eingabe bleibt unsichtbar, auch beim Einfügen; anschließend Enter drücken.

**Falls der Download scheitert:** Modellseite mit demselben Konto öffnen und prüfen,
ob der Zugriff freigegeben ist. Danach Token, Leserechte und vollständiges Einfügen
prüfen. Ein Token allein ersetzt die Modellfreigabe nicht. Bei weiteren geschützten
Modellen gelten die Bedingungen auf deren jeweiliger Modellseite.
[Hilfe zu Modellfreigaben](https://huggingface.co/docs/hub/models-gated).

Den Token wie ein Passwort behandeln und nicht in Screenshots oder Fehlermeldungen
veröffentlichen. Vorhandene Tokens können bei Updates wiederverwendet werden.
Die Modellverarbeitung läuft nach dem Download auf der eigenen Hardware.

## Windows

**Client:** Windows 10/11 x64 und ein Mikrofon. Python und Audio-Laufzeit sind im
Setup enthalten. Fehlende WebView2- und Microsoft-Visual-C++-Laufzeiten richtet
der neue Installer bei Bedarf ein; dafür kann eine Administratorfreigabe nötig sein.

**Eigener KI-Server:** Windows 11 x64, unterstützte NVIDIA-GPU ab 8 GB VRAM,
passender NVIDIA-Treiber und aktivierte CPU-Virtualisierung. WSL/Ubuntu und
benötigte Linux-Komponenten werden eingerichtet. Für diesen Schritt sind
Administratorrechte und gegebenenfalls ein Neustart erforderlich. RAM und
freier Speicherplatz richten sich nach den gewählten Modellen.

1. Die Windows-x64-Setup-Datei aus den [Releases](https://github.com/thomaskien/kienzledoku/releases) laden und starten.
2. Client, Server oder beides wählen. Den Assistenten bis zur Zusammenfassung durchgehen.
3. Installation starten und bis zur abschließenden Prüfung warten.
4. Bei Clientinstallation die angezeigte Adresse in [T2med einrichten](../README.md#t2med-einrichten-und-verwenden).

[Unter Windows installieren](https://www.youtube.com/watch?v=RlPRxwvj6ks)
· [GPU-Unlock unter Windows](https://www.youtube.com/watch?v=k0Zndclce9A)

## macOS

Der grafische Installer ist für **Apple Silicon** vorgesehen. Der lokale
KI-Server benötigt mindestens 16 GB gemeinsamen Arbeitsspeicher; größere Modelle
brauchen mehr. Die Python-Laufzeit ist enthalten. Homebrew oder
Entwicklungswerkzeuge werden für dieses Paket nicht benötigt.

1. Die macOS-arm64-DMG aus den [Releases](https://github.com/thomaskien/kienzledoku/releases) laden und öffnen.
2. **kienzledoku Installation** starten und Client, Server oder beides wählen.
3. Verbindungen, Modelle und Dokumentationsfelder prüfen und die Zusammenfassung bestätigen.
4. Bei Clientinstallation die angezeigte Adresse in [T2med einrichten](../README.md#t2med-einrichten-und-verwenden).

Das Paket ist **lokal signiert, aber noch nicht von Apple notarisiert**.
„Lokal signiert“ bedeutet **keine Bindung an einen bestimmten Rechner**:
KienzleDoku lässt sich auch auf einem anderen kompatiblen Mac mit Apple Silicon
installieren. Der ältere Intel-Clientweg aus dem Quellcode ist im
[Archiv](archiv/direktbetrieb.md) eingeordnet; das ARM-Paket ist kein Intel-Installer.

### Wenn macOS den ersten Start blockiert

Wird der Start wegen fehlender Notarisierung oder eines nicht bestätigten
Entwicklers blockiert, lässt sich die App normalerweise einzeln freigeben.
Voraussetzung ist, dass Sie der Downloadquelle vertrauen und die App unverändert ist.

1. **kienzledoku Installation** einmal zu öffnen versuchen.
2. **Systemeinstellungen → Datenschutz & Sicherheit** öffnen und nach unten scrollen.
3. Bei der Meldung zur App **Dennoch öffnen** wählen.
4. Im folgenden Dialog den Start mit **Öffnen** bestätigen.

[Apple-Anleitung: Sicher Apps auf dem Mac öffnen](https://support.apple.com/de-de/102445).

[Unter Mac und Linux installieren](https://www.youtube.com/watch?v=_Mn_QjbPdmc)

## Linux

Vorgesehen für **Ubuntu 24.04 LTS x86_64**. Der lokale KI-Server benötigt eine
unterstützte NVIDIA-GPU ab RTX 20 mit mindestens 8 GiB VRAM und 20 GiB RAM,
einen funktionierenden NVIDIA-Treiber sowie Speicherplatz für die ausgewählten
Modelle. Der Client benötigt eine Desktop-Sitzung und ein Mikrofon. Der
Download-Starter benötigt `bash`, `wget` und `python3`.

### Server mit einem kurzen Aufruf installieren

```bash
wget -O install_linux.sh https://kienzledoku.de/install_linux.sh && \
bash install_linux.sh --components server
```

Der Starter ermittelt die neueste veröffentlichte, nicht als Vorabversion
markierte Linux-Ausgabe. Er lädt das fertige Archiv und die zugehörige
SHA-256-Datei, prüft beide, entpackt in ein eigenes temporäres Verzeichnis und
startet den enthaltenen Installer. Bei fehlendem Paket, Downloadfehler oder
abweichender Prüfsumme endet er vor der Installation.

Die verwendeten Dateien stammen aus demselben Release; eine reine Windows-Ausgabe
verändert die Auswahl des Linux-Pakets nicht.

### Client mit einem kurzen Aufruf installieren

Am Arbeitsplatz mit Desktop-Sitzung und Mikrofon als angemeldeter Benutzer ausführen:

```bash
wget -O install_linux.sh https://kienzledoku.de/install_linux.sh && \
bash install_linux.sh --components client
```

Der Client benötigt die Adresse des vorhandenen KI-Servers und die T2med-Anbindung.
Auch dieser Aufruf wartet auf ein freigegebenes Linux-Paket. Nicht als root starten.

### Weitere Komponentenauswahl

Ohne Komponentenvorgabe öffnet der Installer seine Auswahl:

```bash
bash install_linux.sh
```

Für **Client** oder **beides** den Starter als angemeldeter Desktop-Benutzer
aufrufen. Systemrechte fordert der Installer bei Bedarf über `sudo` an. In einer
Root-Shell ausschließlich `--components server` verwenden. Ein Wechsel nach
`/root` ist nicht erforderlich.

### Bereits heruntergeladenes Paket

Wer das Archiv und dessen `.sha256`-Datei manuell aus demselben Release lädt,
prüft die Prüfsumme, entpackt das Archiv und startet darin `./install_linux.sh`.
Der im Paket enthaltene Installer und der Download-Starter haben denselben Namen;
der Starter lädt das Paket, der enthaltene Installer führt die Einrichtung aus.

[Unter Mac und Linux installieren](https://www.youtube.com/watch?v=_Mn_QjbPdmc)
· [Quellcode des Download-Starters](../bootstrap/install_linux.sh)

## Modelle und Verbindungen

Der Assistent zeigt die zur Hardware passenden Modelle und die Stufen
**Basis**, **Gründlich** und **Sehr gründlich**. Modelle, Felder und Prompt
werden am Commander eingerichtet. Der Client verwendet dessen gemeinsame
Adresse, normalerweise `http://SERVER:8185` – keine einzelnen KI-Dienstadressen.

Internet wird für benötigte Komponenten und Modelle gebraucht. Geschützte
Hugging-Face-Modelle erfordern die Annahme der Modellbedingungen und ein
Lesetoken: [Hugging-Face-Token Schritt für Schritt einrichten](#hugging-face-token-einrichten). Vorhandene Tokens und Konfigurationswerte werden bei Updates als
Vorgaben übernommen; Tokenwerte nicht in Screenshots oder Protokollen weitergeben.

[Benchmarks und Modelle](https://kienzledoku.de/benchmarks.html)
· [Grafikkartenauswahl](https://kienzledoku.de/grafikkarten.html)

## Aktualisieren und deinstallieren

Vor einem Update offene Aufnahmefenster regulär abschließen. Den freigegebenen
Installer erneut starten und die gewünschten Komponenten wählen. Vorhandene
Einstellungen und Modelle sollen erhalten bleiben; die Zusammenfassung vor dem
Start kontrollieren. Die praktische Prüfung auf dem Zielsystem gehört zur Abnahme.

Über den Deinstallationsbereich des Assistenten lassen sich Client, Server oder
beide Komponenten gezielt entfernen. Modelle und technische Einstellungen werden
nur nach gesonderter Auswahl entfernt. Beim Linux-Installer im entpackten Paket:

```bash
./install_linux.sh --uninstall --components server
```

Für `client` und `both` als Desktop-Benutzer starten. Offene Aufnahmen nicht durch
eine Deinstallation beenden.
