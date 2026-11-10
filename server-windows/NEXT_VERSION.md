# Installer-Anforderungen und Korrekturen

## Korrektur in 1.12: Startabbruch bei „Archiv“ / System.Int32

Der Screenshot vom 04.11.2026, 19:07:33 zeigt einen Abbruch beim Erstellen
der Startseite. Im seit 1.10 ergänzten Hinweistext wurden typografische
einfache Anführungszeichen innerhalb eines einfach begrenzten PowerShell-
Texts verwendet. PowerShell zerlegt den Text dadurch in weitere Argumente;
„Archiv“ wird an den ganzzahligen X-Parameter des Label-Helfers gebunden.
Der Code ist syntaktisch gültig, deshalb erkannte der bisherige Syntaxcheck
die Regression nicht. Die veröffentlichte EXE-Nutzlast von 1.10 und 1.11
reproduziert denselben Fehler im neuen Argumenttest.

1.12 verwendet innere doppelte ASCII-Anführungszeichen. Der neue Test führt
alle tatsächlichen Text-/Steuerelementaufrufe mit den ursprünglichen
typisierten Helferparametern aus, ersetzt nur die Forms-Konstruktion und
prüft außerdem alle Katalogmodelle sowie alte/neue gespeicherte Optionen.
Dies ist eine portable Prüfung unter Linux; eine tatsächlich ausgeführte
Windows-Oberfläche wird damit nicht behauptet. Die Korrektur ändert keine
Modelle, Laufzeit, Bereinigungsregeln oder Administrator-Wiederholung.

## Umsetzung in 1.11: Administratorabfragen unbegrenzt wiederholen

Benutzerfreigabe vom 04.11.2026: Bei nicht bestätigter Administratorabfrage
30 Sekunden warten, den Vorgang protokollieren und erneut anfragen, bis die
Bestätigung gelingt. Dies gilt gleichermaßen für WSL-Voraussetzungen und
Netzwerkkonfiguration. Nur die Administratoranforderung wiederholen; keine
bereits abgeschlossenen Modell-, Installations- oder Prüfschritte neu starten.

- Bei nativem Fehler 1223 den Text „Administrator nicht bestätigt; neuer Versuch
  in 30 Sekunden.“ samt betroffenem Schritt und Versuchsnummer protokollieren.
- Kein festes Versuchslimit. Die 30-Sekunden-Pause ist gezielt abbrechbar.
- „Nein“ und eine abgelaufene Anfrage können denselben Rückgabecode 1223 haben.
  Deshalb in beiden Fällen erneut anfragen. Endgültiger Abbruch erfolgt im
  Assistenten während der Pause über „Abbrechen“.
- Andere Startfehler sowie Fehler des bereits bestätigten administrativen
  Helferprozesses bleiben eigenständige Fehler. Rückgabe 3010 bleibt ein
  Neustarthinweis.
- Start-Process kann native Win32-Fehler in reine Fehlermeldungen umwandeln.
  Den unveränderten Windows-Shell-/runas-Mechanismus direkt über .NET starten,
  um den tatsächlichen NativeErrorCode auszuwerten. Keine UAC-Umgehung.
- GUI-Abbruchmarker sind je Ausführung getrennt und werden zwischen den
  Warteintervallen sowie vor weiteren Abfragen geprüft. Abbruch beendet den
  Vorgang ohne abschließende Bereinigung der Modell-Zwischenkopien.


## Umsetzung in 1.10: Bereinigung, lokale Wiederverwendung und wählbare Dateiprüfung

Benutzerfestlegung vom 04.11.2026: zunächst nur vorgemerkt, anschließend
mit „dann bitte jetzt umsetzen“ ausdrücklich freigegeben. Die Ausgabe heißt
**1.10**, nicht 2.0. Die folgenden Anforderungen sind in 1.10 umgesetzt.

- Im Assistenten ausdrücklich fragen, ob die zusätzlich angelegten lokalen
  Windows-Zwischenkopien nach erfolgreicher Installation bereinigt oder für
  spätere Reparatur/Drüberinstallation behalten werden sollen. Beide Optionen
  anbieten; keine stillschweigende automatische Löschung.
- Nur bei gewählter Bereinigung und erfolgreich abgeschlossener Installation
  einschließlich erfolgreicher Modellübernahme im gewählten Prüfmodus aufräumen.
  Bei Fehler oder Abbruch die Zwischenkopien für die Fortsetzung behalten.
- Bei Behalten diese lokalen Dateien bei späteren Installationen vorrangig
  wiederverwenden. Unveränderte, nachweislich geprüfte Kopien weder erneut aus
  dem Installer-Store/Netzlaufwerk übertragen noch erneut aus dem Internet
  herunterladen. Den Bestand in WSL ebenfalls weiter berücksichtigen.
- Lange Lesezugriffe auf den Netz-Store ebenfalls vermeiden: zuerst den lokalen
  und WSL-Bestand auswerten, den Store nur für tatsächlich fehlende Dateien
  heranziehen. Eine bloße Platzschätzung soll keinen unnötigen vollständigen
  Prüfsummenlauf über bereits lokal vorhandene Modelle im Netzarchiv auslösen.
  Wiederholte Dateiabfragen bündeln und gültige Prüfnachweise nutzen.
- Im Fortschritt zwischen Bestandsabfrage, wiederverwendetem Prüfnachweis,
  vollständiger Prüfsummenberechnung, Kopieren und Download unterscheiden.
  Bei erneuter Vollprüfung den Grund nennen, damit ein langer Hashlauf nicht
  als stillstehende Platzprüfung oder vermeintlicher Neudownload erscheint.
- Erfolgreiche Prüfnachweise mit den bisherigen Dateimerkmals- und
  Sollprüfsummenregeln wiederverwenden. Neue, veränderte oder unvollständige
  Dateien bei aktivierter Inhaltsprüfung prüfen und nur bei Bedarf übertragen;
  eine ausdrücklich gewählte vollständige Neuprüfung bleibt möglich.
- Ergänzter Benutzerwunsch vom 04.11.2026: Checkbox **„Modelldateien per
  Prüfsumme prüfen“**, standardmäßig aktiv und ausdrücklich abwählbar.
  Abgewählt: keine vollständigen SHA-/Inhaltsprüfungen der Modellgewichte,
  einschließlich Whisper und pyannote, weder im Store noch bei lokalen
  Zwischenkopien oder beim WSL-Import. Nur Vorhandensein und erwartete
  Dateigröße für Bestandsauswahl und Übernahme kontrollieren. Die Platzprüfung
  darf in diesem Modus ebenfalls keine versteckte Vollprüfung auslösen.
- Die Auswahl für spätere Reparaturen speichern. „Erneut vollständig prüfen“
  bei abgeschalteter Inhaltsprüfung deaktivieren, damit sich die Optionen nicht
  widersprechen. Die gesonderte synthetische Server-Abschlussprüfung bleibt
  eine eigene Auswahl und wird durch diese Checkbox nicht geändert.
- Übersprungene Inhaltsprüfungen im Ergebnis/Protokoll klar kennzeichnen und
  niemals als erfolgreich geprüfte SHA-Prüfnachweise speichern. Vorhandene
  echte Prüfnachweise erhalten; veränderte ungeprüfte Kopien nicht als geprüft
  ausgeben. Bei deaktivierter Prüfung ist eine inhaltsgleiche Beschädigung
  trotz korrekter Dateigröße nicht durch die Dateiübernahme nachgewiesen.
- Bereinigung betrifft ausschließlich die zusätzlichen, vom Installer selbst
  angelegten Zwischenkopien. Die aktive WSL-Modellablage und das bewusst
  gewählte Modellarchiv auf SSD/Netzlaufwerk bleiben erhalten. Auch bei
  identischen oder überlappenden Pfaden das Modellarchiv nicht löschen.
- Die Versionsvalidierung akzeptiert laufende Unterversionen wie **1.10**.
  Produkt-/Dateiversion, EXE, ZIP und Konfigurationsversion verwenden 1.10.
- Die Startseite durchsucht automatisch nur lokale Quellen. „Archiv prüfen“
  lädt den Netzbestand ausdrücklich nach. Eine Installation startet den
  Store-Zugriff erst für tatsächlich noch benötigte Dateien.
- Ein Importnachweis mit Laufkennung und Prüfmodus schützt die Bereinigung.
  Herkunftszuordnung, unveränderte Dateiidentität, Pfadüberschneidungen,
  Verknüpfungen und auf denselben Rechner zeigende Netzfreigaben berücksichtigen.
  Unbekannte Dateien oder unklar aufgelöste Archive behalten.

## Erfolgreiche Modellprüfungen wiederverwenden

Benutzerwunsch vom 31.10.2026: Bereits erfolgreich geprüfte Modelldateien
sollen bei weiteren Installationsversuchen und nach Neustarts nicht erneut
vollständig eingelesen und gehasht werden. Die wiederholten Prüfungen dauern
insbesondere bei großen Modellen und Netzlaufwerken unverhältnismäßig lange.

- Erfolgreiche Integritätsprüfungen dauerhaft pro Datei speichern.
- Bei unveränderten Dateien das gespeicherte Prüfergebnis übernehmen und im
  Assistenten bzw. Protokoll als bereits geprüft kennzeichnen.
- Den Nachweis an Dateipfad bzw. Dateiidentität, Größe, Änderungsmerkmale und
  erwartete Prüfsumme binden. Neue, veränderte oder unvollständige Dateien sowie
  geänderte Soll-Prüfsummen erfordern eine erneute vollständige Prüfung.
- Fehlgeschlagene oder abgebrochene Prüfungen niemals als Erfolg speichern.
- Doppelte Prüfungen unveränderter Dateien innerhalb eines Durchlaufs ebenfalls
  vermeiden. Quellarchiv, lokale Zwischenkopien und WSL-Zieldateien berücksichtigen;
  ein Nachweis für die Quelldatei ersetzt keine Prüfung einer neuen Zieldatei.
- Eine ausdrücklich angeforderte vollständige Neuprüfung weiterhin ermöglichen.

Umsetzung: Windows speichert den Nachweis in
`%LOCALAPPDATA%\kienzledoku-server\model-verifications.json`, WSL in
`/var/lib/kienzledoku-server/model-verifications.json`. Es gibt eine auswählbare
vollständige Neuprüfung. Nachweise werden nach jeder erfolgreichen Datei
gespeichert. Version 1.3 enthielt noch keine geeigneten Dateimerkmale; beim
ersten Lauf mit 1.4 ist deshalb eine erneute vollständige Prüfung erforderlich.

## Fehlerdetails und sichtbares Protokoll

Benutzerwunsch vom 31.10.2026 nach dem Abbruch beim Bereitstellen von llama.cpp:
Das Protokoll bleibt auf der Ergebnisseite sichtbar, bis der Benutzer den
Assistenten schließt. Ein Knopf öffnet das vollständige Protokoll. Die
Hintergrundprozess-Ausgaben werden je Lauf getrennt aufbewahrt. Unerwartete
Prozessabbrüche zeigen Exitcode, letzten Schritt und verfügbare Fehlerausgaben;
ein alter Zwischenstand darf nicht als abschließende Fehlermeldung erscheinen.

Die ursprüngliche Abbruchursache ist mit den vorhandenen Dateien nicht
nachgewiesen. Version 1.4 verbessert die Diagnose; sie behauptet keine
nachgewiesene Behebung dieses unbekannten Auslösers.


## Korrektur in Version 1.5: LAN-Zugriff bei öffentlichem Netzwerkprofil

Am 01.11.2026 belegt: Die Portweiterleitung von 10.0.83.140:8185 nach
127.0.0.1:8185 ist vorhanden und der lokale Health-Endpunkt bereit. Ethernet
ist als Public eingestuft. Die bisherige Firewallregel war auf Private/Domain
beschränkt. Version 1.5 erstellt die gezielt begrenzte Serverregel mit Profile
Any, liest sie aus dem aktiven Regelbestand zurück und kennzeichnet HTTP-Tests
vom Serverrechner ausdrücklich als lokale Prüfungen. IP, TCP-Port und lokales
Subnetz bleiben die Einschränkungen; das globale Netzwerkprofil bleibt erhalten.


## Umsetzung in Version 1.6: explizites Parallelmodell

Benutzerwunsch vom 01.11.2026: Eigene Auswahl, welches LLM gemeinsam mit Whisper
und pyannote vorgehalten wird. Installierte Modelle bleiben seriell anfragbar,
sofern die Hardware dafür reicht. Standardmodell für Anfragen und Parallelmodell
sind unabhängig; optional bleibt kein LLM parallel geladen. Nach serieller
Verarbeitung wird die explizite Auswahl wiederhergestellt.

Modellauswahl und GPU-Freigaben kommen aus dem Katalog. Zusätzliche Katalogmodelle
erscheinen ohne feste Dreierliste; sie benötigen vollständige Metadaten und eine
passende Hardwarefreigabe. Die Status-API unterscheidet konfiguriertes
Parallelmodell (`resident_quality`) und tatsächlich geladenes LLM (`loaded.llm`,
`loaded_llm_label`, `loaded_llm_mode`). Auch während Diarisierungsaufträgen bleibt
das gewählte Parallelmodell geladen.


## Korrektur in Version 1.7: SelectedItem bei Übernahme alter Einstellungen

Der Screenshot vom 01.11.2026, 12:16 Uhr, zeigt den Abbruch noch vor dem
Installationsstart. Eine nicht präfixierte Datenvariable `$default` überschrieb
das gleichnamige Steuerelement `$script:Default`. Die Variable wurde in
`$previousDefaultModelId` umbenannt. Die echten Startanweisungen aus der
veröffentlichten 1.6-EXE reproduzieren den Fehler. Sechs gezielte Migrationstests
prüfen vorhandene 1.4/1.5-Einstellungen, explizite Parallelmodelle, alle-seriell
und Neuinstallation. Auf Skriptebene prüfen, damit keine Funktionshülle den
Namenskonflikt verdeckt. Laufzeit, Modelle und Client werden nicht verändert.


## Erweiterung in Version 1.8: drei zusätzliche Gemma-4-Modelle

Benutzerfreigabe vom 03.11.2026: Gemma 4 12B Q8_0, 12B QAT Q4_0 und
26B-A4B QAT Q4_0 zusätzlich zu allen bisherigen Modellen aufnehmen.
Die Quellen sind revisionsgebunden und anhand öffentlicher Publisher-Metadaten
auf Dateigröße und SHA256 geprüft. Der bestehende llama.cpp-Stand b9637
(aedb2a5) unterstützt Gemma 4; native GGUF-Chatvorlage und deaktiviertes
Thinking bleiben aktiv. Separate API-IDs, Download/SSD-/Netzimport und
Parallelmodellauswahl werden über den bestehenden dynamischen Katalog bedient.
Parallelprofile: 12B QAT Q4 ab 16 GiB, 12B Q8 und 26B-A4B QAT Q4 ab 24 GiB.
Windows-GPU-Leistungsmessungen dieser Ausgabe sind ausdrücklich noch offen.


## Korrekturen in Version 1.9: inkrementelle Platzprüfung und Fehlerauswertung

Benutzerprotokoll vom 04.11.2026: 1.8 installiert und prüft alle sechs Modelle
mit Gemma 12B Q8 als Parallelmodell erfolgreich. Die spätere UAC-Anforderung
für LAN wird nicht bestätigt; bei Wiederaufnahme verlangt 1.8 nochmals die
volle Belegung plus 35 GiB, obwohl die Komponenten bereits vorhanden sind.
1.9 rechnet nachgewiesene WSL- und Windows-Dateien an, gruppiert den zusätzlichen
Bedarf nach tatsächlichem Datenträger, prüft die WSL-Dateisystemreserve und
verwendet bei vollständig vorbereiteter Laufzeit 5 GiB Arbeitsreserve.
Bei Netzquellen nur noch für benötigte WSL-Dateien lokale Zwischenkopien anlegen.
Frische/unvollständige Installationen behalten die 35-GiB-Laufzeitreserve.

Ein expliziter fertiger Fehlerstatus bleibt maßgeblich. Fehlende Exitcodes nicht
als 0 interpretieren; Prozesshandle beim Start halten und WaitForExit vor der
Ergebnisauswertung. Die konkrete Ursache des im Benutzerprotokoll zusätzlich
angezeigten Exitcodes 0 ist dort nicht direkt aufgezeichnet; null-Konvertierung
und die widersprüchliche Ergebnislogik sind lokal reproduzierbare Schwachstellen.
UAC-Abbruch/Timeout 1223 wird gezielt erklärt. Keine Windows-Administratorabfrage
umgehen. Modelle, KI-Laufzeit und Client bleiben unverändert.
