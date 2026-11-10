# Windows-Server-Installer

- Benutzerfestlegung: Die aktuelle Ausgabe ist **1.12**. Die Unterversion als
  laufende Nummer führen: als Nächstes **1.13**, danach 1.14. Keine Umstellung
  auf 2.0 und keine Patch-Ausgaben wie 1.0.1 ohne Benutzerwunsch.
- Die Umsetzung von **1.10** und **1.11** wurde vom Benutzer ausdrücklich freigegeben.
  Einzelheiten und ursprüngliche Anforderungen stehen in `NEXT_VERSION.md`.
- `VERSION` ist die zentrale Versionsquelle. EXE, ZIP, Assistent,
  Installationsdaten, Dateiversion und Buildnachweis müssen dazu passen.
- Erfolgreiche Modellprüfungen werden seit **1.4** wiederverwendet. Dateipfad,
  Größe, Änderungsmerkmale und Soll-Prüfsumme müssen übereinstimmen. Neue Kopien
  separat prüfen; die manuelle vollständige Neuprüfung beibehalten.
- Das Installationsprotokoll auf der Ergebnisseite sichtbar lassen. Ein
  unerwarteter Prozess-Exit ohne Abschlussstatus ist ein Fehler; Exitcode,
  letzten Schritt und umgeleitete Prozessausgaben aufbewahren und anzeigen.
- PowerShell-Variablen unterscheiden nicht zwischen Groß-/Kleinschreibung.
  Bei Skriptstart und Einstellungsübernahme keine Datenvariable mit dem Namen
  eines Steuerelements verwenden: `$default` überschreibt `$script:Default`.
  Den Migrationstest auf Skriptebene ausführen; eine Funktionshülle kann den
  Fehler durch ihren zusätzlichen Gültigkeitsbereich verdecken.
- Fehlerkorrekturen selbstständig vollständig umsetzen, prüfen, bauen und die
  neue Ausgabe im bereits verwendeten Netzordner unter neuem Versionsnamen
  bereitstellen. Bestehende Modellarchive und ältere Ausgaben behalten.
- Windows-/WSL-/GPU-Prüfungen nur als ausgeführt bezeichnen, wenn sie tatsächlich
  auf Windows liefen. Linux-Prüfungen und Simulationen ausdrücklich benennen.
- Nur Serverkomponenten bearbeiten. Client und bestehender Linux-Installer
  bleiben separate Projekte.
- Seit **1.6** sind Anfrage-Standardmodell und parallel vorgehaltenes Modell
  unabhängig. Die explizite `ParallelModel`-Auswahl benennt genau ein
  installiertes, für die GPU freigegebenes Modell oder ist leer (alle seriell).
  Nach seriellen Aufträgen dieses Modell wiederherstellen. Modelllisten und
  Freigaben aus dem Katalog lesen; keine feste Dreierliste ergänzen.
- Commander-Status: `loaded.llm` ist das tatsächlich geladene Modell,
  `resident_quality` das konfigurierte Parallelmodell, `loaded_llm_label` sein
  aktueller Modellname und `loaded_llm_mode` die Betriebsart. Alte Konfigurationen
  ohne explizites Parallelmodell weiter nach der bisherigen Regel behandeln.
- Die ausdrücklich ausgewählte LAN-IP erhält seit **1.5** eine Firewallregel
  für alle Windows-Netzwerkprofile (`Any`), weiterhin nur TCP 8185 und
  `LocalSubnet`. Das Windows-Netzwerkprofil selbst nicht ändern. Die aktive
  Regel nach dem Anlegen auslesen. Lokale HTTP-Checks nicht als tatsächliche
  Erreichbarkeitsprüfung von einem anderen Rechner aus bezeichnen.
- WSL-Verwaltungsschalter niemals pauschal in Anführungszeichen setzen. Der
  Microsoft-Parser vergleicht die rohen Tokens. Quote nur leere Argumente und
  Werte mit Leerraum/Anführungszeichen. Den Parser-Regressionscheck mitführen.

- Seit **1.8** enthält der Katalog zusätzlich Gemma 4 12B QAT Q4_0, 12B Q8_0
  und 26B-A4B QAT Q4_0. Vorhandene Qwen-Einträge und API-IDs beibehalten.
  Gemma-API-IDs: `gemma12_qat_q4`, `gemma12_q8`, `gemma26_qat_q4`.
  16/24/24 GiB sind konfigurierte Parallelprofile; einen Windows-Benchmark
  dieser Profile erst nach tatsächlicher Ausführung behaupten.

- Seit **1.9** bei Reparatur nur zusätzliche Modellkopien und Volumenbudgets
  berechnen. Unveränderte WSL-Prüfnachweise lesen, keine Modellgewichte für die
  WSL-Kapazitätsschätzung erneut hashen. Tatsächlichen WSL-Registrierungspfad
  berücksichtigen. Vorbereitete Laufzeit: 5 GiB Reserve; neu/unvollständig: 35 GiB.
  Netz-Zwischenkopien nur für WSL-Dateien anlegen, die noch benötigt werden.
- Fehlender Prozess-Exitcode bleibt null. Expliziten abgeschlossenen Fehlerstatus
  nicht als fehlenden Abschluss darstellen. Kindprozesshandle behalten und vor
  Ergebnisauflösung WaitForExit aufrufen. UAC-Code 1223 bedeutet nicht bestätigte
  Administratoranforderung (Abbruch oder Zeitablauf), keine defekte KI-Installation.

- Seit **1.10** `VerifyModelFiles` (Standard true) und `CleanupModelStaging`
  (Standard false) speichern. Ohne Prüfsummenprüfung nur Existenz/Größe prüfen;
  keine neuen Integritätsnachweise erzeugen. Die synthetische Serverprüfung
  bleibt unabhängig. Manuelle Neuprüfung nur bei aktiver Prüfsummenprüfung.
- Installationsquellen in dieser Reihenfolge: WSL-Bestand, lokale Zwischenkopien,
  lokale Archive/Quellen, erst dann Netz-Store und fehlende Downloads. Beim
  normalen Installieren das Netzarchiv nicht als vollständig gefülltes Ziel
  erzwingen. Reiner Download bleibt ein eigener Modus zum Befüllen des Archivs.
- Nur zugeordnete Zwischenkopien nach erfolgreicher Übernahme und Abschluss
  bereinigen. Importnachweis des aktuellen Laufs, unveränderte Dateiidentität
  und Schutz vor Archivüberschneidungen/Verknüpfungen verlangen. Bei unklarer
  Zuordnung oder Archivauflösung behalten. Keine rekursive Ordnerlöschung.
- Automatischer Bestandscheck der Oberfläche ist lokal. Den Netzbestand nur
  nach ausdrücklich geklicktem „Archiv prüfen“ in die GUI-Bestandsliste laden.

- Seit **1.11** unbeantwortete/abgebrochene Administratoranforderungen mit
  nativem Fehler 1223 unbegrenzt nach je 30 Sekunden erneut anfordern. Nur den
  administrativen Schritt wiederholen, nicht Modelle oder Installation.
  „Nein“ und Ablauf sind über diesen Code nicht zuverlässig unterscheidbar.
- Den Shell-Start für erhöhte Helfer direkt über .NET UseShellExecute/runas
  ausführen, damit NativeErrorCode erhalten bleibt. Andere Startfehler und
  Fehler des bereits genehmigten Helfers nicht als fehlende Zustimmung behandeln.
- Während der Wiederholpause erlaubt „Abbrechen“ einen gezielten Abbruch.
  Abbruchmarker an eine geprüfte AdminRetryId pro Lauf binden; vor einem neuen
  Hauptvorgang unter gehaltenem Vorgangsmutex einen alten Marker entfernen.

- Seit **1.12** die tatsächlichen GUI-Helferaufrufe mit ihren typisierten
  Parametern prüfen. ParseFile allein erkennt keine falsch zerlegten Texte:
  typografische einfache Anführungszeichen können einen mit einfachen
  Anführungszeichen begrenzten Text vorzeitig beenden. Der Startabbruch
  „Archiv“/System.Int32 aus 1.10 und 1.11 ist aus beiden EXE-Nutzlasten
  reproduziert. Den Argumenttest zusätzlich zur Startmigration beibehalten.
