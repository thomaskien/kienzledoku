# Direktbetrieb und ältere Installationswege

[Zur aktuellen Übersicht](../../README.md) · [Aktuelle Installation](../installation.md)

Diese Seite bündelt historische und technische Hintergrundinformationen. Der
normale Einstieg für den gemeinsamen Installer ist die [Connect-Einrichtung in
T2med](../../README.md#t2med-einrichten-und-verwenden). **Direktbetrieb bleibt ein vorhandener Sonderweg**; das
Auslagern dieser Erklärung entfernt keine Programmfunktion.

## Zwei Wege zu T2med

| Weg | Aufrufschema | Key-Verwendung |
| --- | --- | --- |
| Über Connect | `kienzledoku://record` | Der in Connect eingebettete Key |
| Direktbetrieb | `kienzledoku-record://record` | Abhängig vom Paket eingebetteter Hersteller-Key bzw. ausdrücklich eingerichteter Key; öffentliche Quellcode-Builds ohne private Einbindung verwenden den Demo-Key |

Vollständige URL für ausdrücklich gewählten Direktbetrieb:

```text
kienzledoku-record://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}
```

T2med ersetzt die Platzhalter. Der Direktbetrieb braucht keinen laufenden
Connect-Prozess. Die Konfiguration bestimmt den Weg; ein Connect-Ausfall
schaltet ihn nicht automatisch um. Diese T2med-Wege sind unabhängig von der
KI-Anbindung: Im aktuellen gemeinsamen Installer spricht der Client immer mit
Commander.

Connect entfernt eingehende `X-API-Key`-Header und setzt seinen eingebetteten
Key. Methode, FHIR-Pfad, Query, Body, OAuth und fachliche Header bleiben erhalten.
Es lauscht an einem zufälligen Loopback-Port und verlangt eine private
Sitzungsberechtigung. Patientenlogik, FHIR-Aufbau und Prüfung liegen in Record.

## Ältere Pakete und URLs

Die bisherigen 1.4.3-Pakete verwendeten den Demo-Key und den Eintrag **T2med – Demo**.
Die neuen gemeinsamen Installer verwenden den KienzleDoku-Hersteller-Key;
dafür wird der Produktcode **kienzledoku** aktiviert. Alte Einträge mit
`kienzledoku://?…` sind beim Wechsel auf Connect auf das Muster mit `/record`
zu aktualisieren. Historische Screenshots können noch `Whisper7` zeigen.

Für den Demo-Key galt laut bisheriger Integrationsvorgabe eine Grenze von
100 einzelnen FHIR-Requests je APS-Serverprozess. Diese historische Grenze
ist kein Nutzungslimit der neuen Hersteller-Key-Pakete.

Eigene Direkt-Keys werden im Betriebssystemspeicher hinterlegt: DPAPI,
macOS-Schlüsselbund bzw. Linux Secret Service. Der Entwickler-Override
`KIENZLEDOKU_T2MED_API_KEY` gehört zum Direktbetrieb. Private Schlüsseldateien
und private Build-Quellen gehören niemals in Git oder öffentliche Pakete.

## Ältere Quellcode-Installer

Die früheren Wege `install_macos.command`, `install_linux.sh` und die
Windows-Buildskripte im bisherigen Quellstand haben eigene Voraussetzungen.
Der ältere Mac-Clientweg unterstützt Intel und Apple Silicon mit Python >= 3.9;
er ist nicht der neue grafische ARM-Installer. Ältere getrennte Server-Installer
sind nicht mit dem gemeinsamen Client-/Server-Setup gleichzusetzen.

Die aktuelle Anleitung verwendet fertige, freigegebene Pakete. Den neuen
Download-Starter nicht durch das gleichnamige Skript aus einem beliebigen
älteren Quellcode-Stand ersetzen.

Ältere Record-Ausgaben beschrieben eine lokale Sicherungs- und
Wiederherstellungsfunktion. Der neue gemeinsame Installerstand hält Aufnahme und
Entwurf ausschließlich im RAM und verwirft offene Arbeit beim Schließen.

[Vorherige ausführliche README als datierter Archivstand](readme-vor-2026-11-15.md)
· [Änderungsverlauf](../../CHANGELOG.md)
