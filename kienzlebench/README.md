# Kienzlebench 1.2

Portabler Benchmarker für KienzleDoku-Commander mit Benchmark-Schnittstelle
(zum Beispiel Commander 1.8.1). Die Oberfläche öffnet im vorhandenen Browser;
Installation, Python, Node und Modelldownload sind zum Start nicht erforderlich.

## Download

Die drei einzelnen Programmdateien und Prüfsummen stehen im
[Release Kienzlebench 1.2](https://github.com/thomaskien/kienzledoku/releases/tag/kienzlebench-v1.2):

| Plattform | Programmdatei |
| --- | --- |
| macOS ab 11, Apple Silicon | `Kienzlebench-1.2-macOS.command` |
| Ubuntu 24.04 LTS, x86_64 | `Kienzlebench-1.2-Linux` |
| Windows 10/11, x64 | `Kienzlebench-1.2-Windows.exe` |

Die Mac-Datei ist lokal signiert, nicht notarisiert. Windows ist nicht
Authenticode-signiert. Unter Linux bei Bedarf das Ausführungsrecht setzen.

## Verwendung

1. Passende Programmdatei starten und die Commander-Adresse eintragen.
   Ohne Commander-Zugangsschutz bleibt das Tokenfeld leer.
2. Vorhandene Modelle und seriellen beziehungsweise parallelen Betrieb auswählen.
3. Optional Whisper und den 30-Minuten-Wärmetest mit einem LLM auswählen.
4. Benchmark starten. Die ausgewählten Modelle werden nacheinander geprüft.
5. Zum Beobachten der Nachkühlung das Fenster geöffnet lassen. Jede weitere
   Minute ergänzt eine CPU-/GPU-Zeile im Bericht und in derselben Textdatei.

Der Hauptbericht enthält Hardwaredaten einschließlich CPU, RAM, Mainboard, SSD
und GPU, kompakte getrennte Vergleichstabellen sowie den Temperaturverlauf.
Anzeige, Kopierfunktion und Textdatei verwenden dieselbe Darstellung.
[Beispielbericht mit fiktiven Daten](examples/bericht-1.2.txt).

Die Commander-Adresse wird in `.kienzlebench.json` neben dem Programm gespeichert;
Tokens bleiben nur im RAM. Ein datierter Textbericht entsteht ebenfalls neben
dem Programm. Ist das Verzeichnis nicht beschreibbar, entfallen beide Dateien
ohne Fehlermeldung. Anzeige und Kopieren funktionieren weiter.

## Messverfahren

- Die beiden festen GP60-Fälle G60_01A (5-Minuten-Kontakt) und G60_30B
  (20-Minuten-Kontakt), je ein ausgeschlossener Erstlauf plus fünf Messungen.
- Median nur bei fünf erfolgreichen Messungen. Die Kontaktlängen sind keine
  Audiodauern. Fehlgeschlagene oder unvollständige Reihen bleiben sichtbar.
- Serielles LLM: bestätigter Ladebeginn bis vollständige Antwort. Parallel:
  Inferenz bei gleichzeitig geladenem LLM und Whisper.
- Whisper: 113,16 Sekunden Referenzaudio, 13 Final-Blöcke ohne Echtzeitpausen.
  Der serielle Vergleich erfordert eine vom Commander bestätigte Ladezeit.
- Wärmetest: ein LLM für 30 Minuten; Whisper/LLM im Wechsel oder gleichzeitig.
  Bereits geladenes Whisper benötigt hierfür keinen erneuten Ladenachweis.
  Reale Anfragefehler bleiben Abbruchgründe.
- Bei vielen schnellen Anfragen werden Benchmarksitzungen vor der
  Commander-Auftragsgrenze erneuert. Modell, Betriebsart und Temperatur-Zeitachse
  bleiben gleich; Wiederherstellung und Vorbereitung können kurze Lastpausen erzeugen.
- CPU-/GPU-Werte von Minute 0 bis 30, anschließend eigene Zeitachse für die
  Nachkühlung. Fehlende Sensoren und Werte werden nicht ersetzt. Lastmaxima
  beziehen sich auf Minutenmessungen, nicht auf kontinuierliche Sensormessung.
- Promptcache aus; Betriebssystem-Dateicache unverändert. Kein nachgewiesener
  SSD-Kaltstart und kein fachlicher Qualitätsnachweis durch Zeitmessungen.

## Änderungen und Prüfung

Version 1.2 korrigiert den vorzeitigen seriellen Whisper-Abbruch im Wärmetest,
ersetzt feste Wiederholungsgrenzen durch kontrollierte Sitzungserneuerung und
fasst identische Modellspeicher-Zeilen zusammen. Die Nachkühlung läuft ohne feste
Minutengrenze bis zum Programmende weiter.

25 automatisierte Tests einschließlich Race Detector bestanden. Zusätzlich
wurde die macOS-Datei gegen einen lokalen simulierten Commander geprüft,
einschließlich einer echten Nachkühlungsminute in derselben Berichtsdatei.
Native Windows-/Linux-Starts und ein echter 30-Minuten-Hardwarelasttest sind
noch nicht Teil dieser Abnahme. Tests mit verkürzter Uhr sind keine realen
Temperaturmessungen.

## Entwicklung

Go-Standardbibliothek ohne externe Module. Für die macOS-Untergrenze 11 wird
Go 1.24.13 verwendet. Im Ordner `src`:

```sh
go test -race -count=1 -v ./...
go vet ./...
```

Der optionale Integrationstest benötigt einen separat gestarteten lokalen
Commander mit simulierten Modellen. Ohne `KIENZLEBENCH_TEST_COMMANDER` wird er
übersprungen. Für eine manuelle Oberfläche mit fiktiven Beispieldaten:
`KIENZLEBENCH_UI_PREVIEW=1 go test -run TestUIPreview -v`.

`python3 build.py --go /pfad/zu/go` baut auf macOS alle drei Plattformen nach
`dist/1.2/`. Vorhandene Ausgaben werden nicht überschrieben. Audio, GP60-Fälle,
HTML, CSS und JavaScript werden unverändert eingebettet.

## Referenzaudio und Lizenz

Referenz: **„Der Husten geht nicht weg“**, [Hörtexte Deutsch](https://www.hoertexte-deutsch.at/mp3/husten.mp3).
Lizenz laut Referenzprotokoll: [CC BY-NC-ND 3.0 AT](https://creativecommons.org/licenses/by-nc-nd/3.0/at/).
Die vollständige PCM-Referenz bleibt unverändert; Blockbildung erfolgt nur im
Arbeitsspeicher. Herkunft, Format und Prüfsummen stehen in
`src/assets/audio-provenance.json`. Diese Drittinhalte fallen nicht unter die
MIT-Lizenz des Programmquellcodes; ihre gesonderten Lizenzbedingungen gelten.
