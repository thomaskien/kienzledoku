# kienzledoku Server Installer 1.12

Eigenständiges Windows-Setup für die **Serverkomponenten** von Kienzledoku.
Es installiert eine eigene Ubuntu-24.04-WSL2-Umgebung mit Whisper large-v3,
pyannote Community-1, llama.cpp und Commander. Der Arbeitsplatzclient und
T2med bleiben separat. Vorhandene Linux-Installationen werden nicht angesprochen.

## Start

`dist/kienzledoku-Server-Installer-1.12.exe` unter Windows 11 x64 öffnen.
Alternativ das gleichnamige ZIP entpacken und die EXE darin starten.
Der Assistent nutzt Windows PowerShell 5.1 und Windows Forms; Python muss auf
Windows nicht vorinstalliert sein. Das Setup ist nicht digital signiert.

CPU-Virtualisierung (Intel VT-x beziehungsweise AMD SVM) muss im UEFI/BIOS
eingeschaltet sein. Für die eigene WSL-Umgebung sind ein beschreibbares lokales
Laufwerk, ausreichend Platz für die aktiven Modellkopien und zusätzliche
Laufzeitpakete erforderlich. Der Assistent prüft den verfügbaren Platz.

Die erste Auswahl lautet **Server installieren/reparieren** oder **nur Modelle
herunterladen**. Der reine Download benötigt weder WSL noch Administratorrechte.
Die Startseite zeigt lokale Modellbestände anhand von Vorhandensein und Größe.
Netzarchive werden erst über **„Archiv prüfen“** abgefragt. Der WSL-Bestand wird
bei der Ausführung berücksichtigt. Die eigentliche Übernahme folgt dem unten
beschriebenen, ausdrücklich wählbaren Prüfmodus.

Der Hugging-Face-Read-Token ist im Eingabefeld ausdrücklich **sichtbar**. Er wird
geschützt im Benutzerprofil gespeichert und aus Protokollen ausgeschlossen.
Die Bedingungen des Modells `pyannote/speaker-diarization-community-1` müssen
vorher im zugehörigen Hugging-Face-Konto akzeptiert sein. Der Assistent prüft
den tatsächlichen Zugriff, wenn ein fehlendes zugriffsbeschränktes Modell
heruntergeladen werden muss. Für vollständig vorhandene Modelle wird kein
erneuter Hugging-Face-Zugriff verlangt.

## Modelle und Grafikspeicher

| Modell | Seriell, volle GPU-Auslagerung | Parallel mit Audio geladen |
|---|---:|---:|
| Qwen3.5-9B Q4_K_M | 8 GiB VRAM | 16 GiB VRAM |
| Qwen3.5-9B Q6_K | 12 GiB VRAM | 20 GiB VRAM; 24-GB-Karte empfohlen |
| Qwen3.8-27B UD-Q4_K_M | 20 GiB VRAM; 24-GB-Karte empfohlen | Nicht freigegeben |
| Gemma 4 12B QAT Q4_0 | 8 GiB VRAM | 16 GiB VRAM |
| Gemma 4 12B Q8_0 | 16 GiB VRAM | 24 GiB VRAM |
| Gemma 4 26B-A4B QAT Q4_0 | 20 GiB VRAM | 24 GiB VRAM |

Beispielgrößen: RTX 2070 SUPER 8 GB für Q4 seriell; RTX 5060 Ti **16 GB**
für Qwen 9B Q4 oder Gemma 12B QAT Q4 parallel geladen; RTX 3090/4090 24 GB
für Gemma 12B Q8 oder Gemma 26B-A4B QAT Q4 parallel geladen.
Die Gemma-Parallelprofile sind für diese Ausgabe konfigurierte Planungswerte;
der Windows-/WSL-GPU-Benchmark folgt separat. Seriengrenzen sind konservative
Installerprofile, keine Messung des absoluten Speicher-Minimums.
Die VRAM-Größe allein bestimmt nicht die Geschwindigkeit. CUDA 13 benötigt
Compute Capability mindestens 7.5 und einen passenden Windows-NVIDIA-Treiber.
Der Installer installiert ausschließlich das CUDA-Toolkit **innerhalb von WSL**,
keinen Linux-Grafiktreiber und keinen Windows-Grafiktreiber.

Alle Profile verwenden 32.768 Token Kontext, einen LLM-Slot und deaktiviertes
Thinking. **Parallel** bedeutet gleichzeitig geladen; es ist keine Zusage
beliebiger gleichzeitiger Inferenz oder mehrerer LLMs auf derselben GPU.
Immer nur das jeweils aktive LLM ist geladen. Die Modellauswahl legt fest,
welche Modelle installiert werden und danach seriell angefragt werden können.
Deren serielle GPU-/RAM-Voraussetzungen gelten weiterhin.

Unter **„Parallel vorgehaltenes Modell“** wird unabhängig davon genau ein Modell
gewählt, das zusammen mit Whisper und pyannote bereitgehalten wird. Die Liste
zeigt die installierbaren Auswahlen mit freigegebenem Parallelprofil für die
gewählte GPU. **„Keines — alle LLMs seriell“** hält kein LLM im Grundzustand geladen.
Alle anderen installierten LLMs werden seriell verarbeitet; nach dem Auftrag
kehrt der Commander zum gewählten Parallelmodell zurück. Dieses bleibt auch bei
ASR- und Diarisierungsaufträgen geladen. Das **Standardmodell für Anfragen** ist
separat wählbar und wird verwendet, wenn der Client kein Modell angibt.

Beispiel: Q6 als Parallelmodell, Q4 als Anfrage-Standard und 27B zusätzlich
installiert. Im Grundzustand sind Q6 und die Audiomodelle geladen. Q4- oder
27B-Anfragen werden seriell bearbeitet; anschließend wird Q6 wiederhergestellt.

Die Auswahl wird aus `models.json` aufgebaut. Weitere Modelle können mit eigener,
eindeutiger API-ID (`quality`), Bezeichnung, festen Quelldateien und Prüfsummen,
32k-/Ein-Slot-Laufzeitprofil sowie seriellen und optionalen parallelen
VRAM-Grenzen ergänzt werden. `parallel_vram_mib: null` bedeutet seriell ohne
freigegebenen Parallelbetrieb. Optionale `fallbacks` enthalten API-Modell-IDs;
`ram_audio_min_wsl_gib` beschreibt die RAM-Anforderung ohne Whisper-SSD-Sparmodus.
Neue Modelle benötigen diese Angaben und eine passende Hardwarefreigabe.

## WSL-Speicher und Windows-Reserve

Diese Angaben sind **WSL-RAM**, nicht der Gesamtspeicher des Rechners:

| WSL-Obergrenze | Vorgesehene Verwendung |
|---|---|
| 16 GiB | Parallelbetrieb bei passendem VRAM-Profil; seriell mit begrenztem LLM-Dateicache |
| 24 GiB | Empfehlung für seriell gecachtes 9B Q4 / Gemma 12B QAT Q4 |
| 28 GiB | Mehr Cache-Reserve für seriell gecachtes 9B Q6 / Gemma 12B Q8 |
| 32 GiB | Empfehlung für seriell gecachtes Qwen 27B / Gemma 26B-A4B QAT Q4 |

Standardmäßig bleiben die vorhandenen Audiomodellobjekte und geparkten Gewichte
im RAM. Der zusätzliche **Whisper-SSD-Sparmodus** entfernt den CT2-Gewichtscache
aus dem RAM und lädt ihn später wieder von SSD. Bei 27B und 16 GiB WSL ist dieser
Sparmodus verpflichtend, weil Audio vollständig im RAM unter diesem Budget nicht
nachgewiesen wurde. Bei Q4/Q6 ist er optional.

Die KI-Slice erhält ein gemeinsames RAM-Limit von WSL-Obergrenze minus 3 GiB
und verwendet keinen Swap. Der Rest ist als Reserve für Linux und Laufzeitcode
eingeplant. Die Windows-Auslagerung anderer Programme wird nicht verändert.

Der Assistent zeigt Gesamtspeicher, WSL-Obergrenze und verbleibendes Windows-Budget.
Mindestens ungefähr 4 GiB Reserve müssen für Windows eingeplant bleiben. Mehr Reserve
ist bei anderen parallel verwendeten Anwendungen sinnvoll. Mehr als 50 Prozent
des Gesamtspeichers können ausdrücklich für WSL eingestellt werden.

**WSL verwaltet das Limit benutzerweit über `.wslconfig`.** Andere Einstellungen
bleiben erhalten; eine bestehende Datei wird vor Änderungen gesichert. Laufende
andere WSL-Instanzen werden nicht beendet. Sie müssen vor einer Änderung geschlossen
werden. Die eigene Umgebung heißt `kienzledoku-server`; vorhandene andere
Distributionen werden nicht verwendet oder überschrieben.

Die Budgets sind aus Linux-Messungen abgeleitete Planungswerte. Eine erfolgreiche
Prüfung auf dem konkreten Windows-Rechner ist weiterhin erforderlich.

## Tragbare Modellablage und Netzlaufwerke

Das Modellarchiv liegt standardmäßig **neben der EXE im Unterverzeichnis `models`**:

```text
kienzledoku-Server-Installer-1.12.exe
models/
  9b-q4/Qwen_Qwen3.5-9B-Q4_K_M.gguf
  9b-q6/Qwen_Qwen3.5-9B-Q6_K.gguf
  27b-q4/Qwen3.8-27B-UD-Q4_K_M.gguf
  gemma12-qat-q4/gemma-4-12b-it-qat-q4_0.gguf
  gemma12-q8/gemma-4-12B-it-Q8_0.gguf
  gemma26-qat-q4/gemma-4-26B_q4_0-it.gguf
  whisper/...
  pyannote/...
```

Das Ziel kann im Assistenten geändert werden. Zusätzliche Quellen lassen sich
zeilenweise angeben, einschließlich `\\Server\Freigabe\models`. GGUF-Dateien
werden auch aus flachen Modellverzeichnissen übernommen. Für Audio können die
jeweiligen vorhandenen Modell-/Snapshotverzeichnisse als eigene Quelle angegeben
werden. Die Prüfsummen verhindern Verwechslungen gleichnamiger Dateien.

Downloads verwenden fortsetzbare `.part`-Dateien und feste Modellrevisionen.
Große Gewichte werden mit SHA-256 geprüft; kleine unveränderte HF-Repositorydateien
zusätzlich mit ihrem veröffentlichten Git-Blob-Hash. Es werden nur ausgewählte LLMs
geladen. Die beiden Whisper-Darstellungen und pyannote werden immer vorbereitet.

Das Archiv kann auf weitere Rechner mitgenommen werden. Für den aktiven Betrieb
werden ausgewählte Modelle ins Linux-Dateisystem der eigenen WSL-Umgebung kopiert.
Damit ist der laufende Server nicht von einer Netzfreigabe abhängig. Das benötigt
Platz sowohl für das aufbewahrte Downloadarchiv als auch für die aktive Kopie.
Eine UNC-Zielablage oder ein zugeordnetes Netzlaufwerk wie `Z:` wird für den
WSL-Import zusätzlich lokal zwischengespeichert. Seit 1.9 betrifft dies nur
Dateien, die in WSL noch nicht nachweislich vorhanden sind. Die zusätzliche
Belegung wird dem jeweiligen Laufwerk zugerechnet; WSL muss das Netzlaufwerk
nicht selbst mounten.
Für WSL, Python-Pakete und Buildwerkzeuge wird weiterhin Internet benötigt;
eine vollständig netzlose Installation ist nicht enthalten.

## Netzwerk und Zugang

Voreinstellung: **nur localhost**, `http://localhost:8185`.
Optional kann genau eine vorhandene IPv4-Adresse ausgewählt werden. Eine
Windows-Portweiterleitung öffnet den Server zusätzlich auf dieser Adresse.
Die Freigabe gilt für die ausgewählte IP, TCP 8185 und das lokale Subnetz.
Seit Version 1.5 gilt diese einzelne Regel für alle Windows-Netzwerkprofile
(`Any`), einschließlich „Öffentlich“. Das Windows-Netzwerkprofil bleibt erhalten;
die Firewall wird nicht global deaktiviert. Die eingerichtete Regel wird aus
dem aktiven Windows-Regelbestand zurückgelesen und auf Aktivierung und Profil
geprüft. Die lokalen HTTP-Prüfungen belegen die Erreichbarkeit auf dem
Serverrechner; der Zugriff von einem separaten Client ist zusätzlich zu prüfen.

Die Linux-API und alle internen KI-Backends bleiben an Loopback gebunden. Der
zusätzliche Windows-Endpunkt leitet ausschließlich zur lokalen API weiter.
Das funktioniert unabhängig davon, ob WSL mit NAT oder gespiegeltem Netzwerk läuft,
sofern Windows auf den lokalen WSL-Endpunkt zugreifen kann. Eine Änderung der
gewählten Netzwerk-IP erfordert erneutes Konfigurieren im Assistenten.

Der Server erzeugt einen eigenen Client-Zugangstoken. Serveradresse und dieser
Token erscheinen am Ende zur Übernahme in den separat installierten Client.
Der HF-Token ist davon unabhängig. Keine Clientdateien, URL-Handler oder
T2med-Installationen werden erstellt.

## Installation, Wiederaufnahme und Betrieb

WSL-Aktivierung und Netzwerkfreigabe verlangen gegebenenfalls Windows-UAC.
Die Installation gehört weiterhin dem aufrufenden Windows-Benutzer. Bei notwendigem
Neustart erscheint ein entsprechender Hinweis. Danach unter
**Startmenü → kienzledoku Server → Installation fortsetzen** weitermachen.
Alternativ dieselbe EXE erneut öffnen. Vollständig geprüfte Modelldateien und
abgeschlossene Paket-/Buildphasen werden wiederverwendet.
Die Fortsetzung ist manuell: Assistent öffnen, Einstellungen prüfen und „Jetzt
ausführen“ wählen. Seit 1.4 werden erfolgreiche Prüfsummen dauerhaft pro Datei
gespeichert. Unveränderte Dateien werden danach ohne erneutes vollständiges
Einlesen übernommen. Neue, veränderte und unvollständige Dateien sowie geänderte
Soll-Prüfsummen werden vollständig geprüft. Neue Kopien erhalten einen eigenen
Nachweis. Unter „Modelle auswählen“ lässt sich eine vollständige Neuprüfung
ausdrücklich anfordern. Beim ersten Lauf mit 1.4 ist einmal eine vollständige
Prüfung nötig, weil 1.3 noch keine passenden Dateimerkmale gespeichert hat.

Bereits aktivierte Windows-Komponenten und eine vorhandene moderne WSL-Version
werden wiederverwendet. Fehlt WSL, folgt die Installation ohne Standarddistribution,
danach die eigene Ubuntu-Umgebung. Falls der WSL-Bootstrap trotz installierter
Laufzeit einen Fehlercode zurückgibt, wird die tatsächliche Verfügbarkeit mit
`wsl --version` geprüft. Ohne erfolgreichen Versionsnachweis wird nicht fortgesetzt.

Die Installation kann CUDA-Toolkit, Torch-Pakete und einen GPU-spezifischen
llama.cpp-Build benötigen; der erste Lauf kann entsprechend länger dauern.
Das Fortschrittsfenster zeigt die aktuelle Phase und das laufende Protokoll.
Während eines laufenden Vorgangs ist Schließen im Assistenten gesperrt. Ein
externer Abbruch kann durch erneutes Ausführen repariert werden.

Startmenüeinträge: **Server starten**, **Server stoppen**, **Serverstatus**,
**Server prüfen**, **Installation fortsetzen**, **Server deinstallieren**.
Autostart ist wählbar und startet **nach der Anmeldung dieses Benutzers**.
Ein Start vor der Windows-Anmeldung ist nicht enthalten.

Eine an Windows angebundene eigene WSL-Sitzung hält die Instanz während des
Serverbetriebs am Leben. Beim Stoppen werden zuerst alle eigenen KI-Dienste
beendet und anschließend nur die eigene WSL-Instanz terminiert. Damit werden
auch deren RAM- und VRAM-Belegungen freigegeben. Andere WSL-Instanzen und
Windows-Grafikprozesse bleiben bestehen.

Am Ende ist der Server standardmäßig gestoppt; „eingeschaltet lassen“ ist wählbar.
Bei GPU-Wechsel auf einer portablen Windows-SSD den Installer erneut ausführen,
damit GPU-Profile und Buildarchitektur zur aktuellen Maschine passen.

Bei Deinstallation: eigene WSL-Umgebung samt aktiven Modellen entfernen **oder**
Server deaktivieren und vorbereitete Umgebung behalten. Modellarchive auf
SSD/Netzlaufwerk werden immer behalten. Eine spätere Wiederverwendung der
behaltenen Umgebung erfolgt über dieselbe Setup-EXE.

## Dateiprüfung, lokale Wiederverwendung und Bereinigung

Seit **1.10** ist **„Modelldateien per Prüfsumme prüfen“** standardmäßig aktiviert.
Gespeicherte Nachweise für unveränderte Dateien werden wiederverwendet. Fehlt ein
passender Nachweis, zeigt das Protokoll die vollständige Prüfung und ihren Grund.
Mit **„Erneut vollständig prüfen“** lässt sich die Wiederverwendung ausdrücklich
übergehen. Diese Auswahl wird bei abgeschalteter Prüfsummenprüfung deaktiviert.

Bei **abgewählter Prüfsummenprüfung** werden bei Modellgewichten nur Existenz und
erwartete Dateigröße kontrolliert: im Store, auf Windows und beim WSL-Import.
Das gilt auch für Whisper und pyannote. Gleich große beschädigte Dateien können
in diesem Modus unerkannt bleiben. Das Ergebnis kennzeichnet den Modus; es werden
keine übersprungenen Prüfungen als echte Integritätsnachweise gespeichert. Die
synthetische Server-Abschlussprüfung ist eine eigene, unabhängige Auswahl.

Beim Installieren/reparieren gilt: **WSL-Bestand → lokale Zwischenkopien → lokale
Archive/weitere Quellen → erst dann Netzarchiv oder fehlender Download.** Sind
alle Modelle bereits nutzbar vorhanden, muss der Store nicht vollständig gelesen
oder erneut befüllt werden. Lokal zugängliche Quellen werden direkt beim Import
verwendet; eine zusätzliche Zwischenkopie entsteht nur bei Bedarf. Der separate
Modus **„Nur Modelle herunterladen“** befüllt weiterhin das ausgewählte Archiv.

**„Nach Erfolg zusätzliche lokale Modell-Zwischenkopien bereinigen?“** ist
standardmäßig abgewählt. Behaltene Kopien werden bei späteren Drüberinstallationen
wiederverwendet. Bei gewählter Bereinigung werden nur zugeordnete, unveränderte
Zwischenkopien gelöscht, deren aktive WSL-Kopie der aktuelle Installationslauf
erfolgreich übernommen hat. Die Prüfung folgt dem gewählten Prüfmodus.
Unbekannte Dateien, aktive WSL-Modelle und bewusst ausgewählte Modellarchive
bleiben erhalten. Überlappende Archivpfade, Verknüpfungen und unklar auflösbare
Netzfreigaben verhindern eine Bereinigung. Alte Zwischenkopien können anhand des
vorherigen Installationsverzeichnisses und seiner Netzquellen zugeordnet werden.
Bei Fehlern vor diesem abschließenden Schritt bleiben die Zwischenkopien erhalten.

Beide neuen Optionen werden für spätere Reparaturen gespeichert. Herkunft und
Dateimerkmale liegen lokal in `staging-files.json`; der WSL-Importnachweis liegt
unter `/var/lib/kienzledoku-server/model-import.json`. Diese enthalten keine
HF-Zugangstoken. Nur Modell-Prüfsummenläufe sind abwählbar; Integritätsprüfungen
von Laufzeit-/Ubuntu-Paketen werden durch die Modelloption nicht verändert.

## Administratorabfragen und Wiederholung

Seit **1.11** wird eine nicht bestätigte Windows-Administratoranforderung bei
Fehler **1223** unbegrenzt wiederholt. Vor jedem neuen Versuch liegen **30
Sekunden Pause**. Das Protokoll und der Assistent zeigen:
„Administrator nicht bestätigt; neuer Versuch in 30 Sekunden.“, ergänzt um
Schritt und Versuchsnummer. Dies gilt für WSL und Netzwerk gleichermaßen.
Nur die Administratoranforderung wird wiederholt; erledigte Modell- und
Installationsschritte werden deswegen nicht erneut ausgeführt.

Ein Klick auf **„Nein“** kann denselben Windows-Code liefern wie eine nicht
rechtzeitig bestätigte Abfrage. Diese Fälle werden daher gemeinsam behandelt.
Zum endgültigen Beenden in der Wartepause im Installer auf **„Abbrechen“**
klicken. Bereits übernommene Modelle und Zwischenkopien bleiben erhalten.
Der Abbruchmarker ist an den aktuellen Lauf gebunden. Während des eigentlichen
Windows-Sicherheitsdialogs bleiben dessen Windows-Bedienelemente maßgeblich.

Die Windows-Zustimmung bleibt erforderlich. Der Installer startet die erhöhten
Helfer mit demselben Shell-/runas-Mechanismus direkt über .NET, damit native
Fehlercodes erhalten bleiben. Andere Startfehler und tatsächliche Fehler nach
bereits erteilter Zustimmung werden nicht endlos wiederholt. Eine erforderliche
Neustart-Rückgabe 3010 wird weiterhin getrennt behandelt. Nach Zustimmung ist
keine eigene feste Laufzeitgrenze für den Helfer gesetzt.

Quellen: [Windows ShellExecuteEx](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexa),
[PowerShell-Quellcode zum Shell-Start](https://github.com/PowerShell/PowerShell/blob/v7.6.9/src/Microsoft.PowerShell.Commands.Management/commands/management/Process.cs).

## Prüfstand dieser Ausgabe

Version **1.12** behebt den Startabbruch aus 1.10 und 1.11 mit der Meldung,
der Wert „Archiv“ könne nicht in `System.Int32` konvertiert werden. Ursache
waren typografische einfache Anführungszeichen im neuen Hinweistext der
Startseite: Sie zerlegten einen syntaktisch gültigen PowerShell-Aufruf in
falsche Argumente. Innere doppelte ASCII-Anführungszeichen beheben den Fehler.

Der neue Argumenttest reproduziert den Fehler aus beiden veröffentlichten
EXE-Nutzlasten. Mit der Korrektur bindet er alle **66 tatsächlichen Aufrufstellen**
für Texte und Steuerelemente an deren ursprüngliche typisierte Parameter.
Er prüft außerdem alle sechs Katalogmodelle und die Übernahme der neuen
Optionen aus alten und neuen Einstellungen. Nur die Forms-Konstruktion wird
simuliert; dies ersetzt keinen praktischen Windows-GUI-Test. Modellquellen,
KI-Laufzeit und die übrigen Installerfunktionen bleiben gegenüber 1.11 gleich.

Version **1.11** ergänzt die oben beschriebene Wiederholung und den gezielten
Abbruch in der Wartepause. Die Modelle, deren Quellen und die KI-Laufzeit werden
gegenüber 1.10 nicht geändert. Die Wiederholung und Zeitabstände sind unter
Linux mit simulierten UAC-Antworten und ohne echte Wartezeiten geprüft;
eine tatsächliche Windows-UAC-Prüfung dieser Ausgabe steht noch aus.


Version **1.10** setzt die oben beschriebenen Optionen und die lokale
Quellenvorauswahl um. Die Versionsnummer wird als Haupt- und laufende Unterversion
geführt; die Windows-Dateiversion lautet **1.10.0.0**. Alle sechs bisherigen
Modellvarianten und ihre Downloadrevisionen bleiben erhalten.


Version **1.9** korrigiert die Platzprüfung bei Wiederaufnahme und Reparatur.
Die bereits belegten Modellkopien werden nicht nochmals als freier Platz
verlangt. Der Installer liest die unveränderten WSL-Prüfnachweise, berücksichtigt
nur zusätzliche Dateien und plant lokale Netz-Zwischenkopien nur für Dateien,
die in WSL noch benötigt werden. Laufwerke für Modellarchiv, Windows-Programm,
Zustandsdaten und den tatsächlich registrierten WSL-Datenträger werden getrennt
geprüft; Anforderungen auf demselben Laufwerk werden addiert. Auch freier Platz
innerhalb von WSL wird geprüft. Eine vorbereitete Laufzeit erhält 5 GiB zusätzliche
Arbeitsreserve, eine neue oder unvollständige weiterhin 35 GiB. Der Ansatz für
WSL-Wachstum auf dem Windows-Datenträger bleibt konservativ.
`%LOCALAPPDATA%\kienzledoku-server\disk-space.json` und das Protokoll enthalten
Bedarf, freien Speicher, wiederverwendeten Bestand und die verwendete Reserve.

Eine nicht bestätigte Windows-Administratoranforderung (Fehler 1223: Abbruch
oder Zeitablauf) nennt den betroffenen Schritt ausdrücklich. Die Sicherheitsabfrage
für Firewall und Portweiterleitung muss auf dem Windows-Desktop bestätigt werden.
Der Installer behält außerdem den Prozesshandle und wartet vor der Ergebnisauswertung
auf das Prozessende. Ein fehlender Exitcode wird nicht mehr in 0 umgewandelt; ein
expliziter Fehlerstatus bleibt eine konkrete Fehlermeldung und wird nicht nochmals
als fehlender Abschluss bezeichnet.

Das vom Benutzer am **04.11.2026** gelieferte Windows-Protokoll belegt für **1.8**:
18 erfolgreiche synthetische Audioketten über alle sechs Modelle ohne Fallback,
Rückkehr zu Gemma 12B Q8 parallel mit Whisper und pyannote sowie einen Kontextlauf
mit 24.282 Eingabetoken. Erst danach wurde die Administratoranforderung für die
Netzwerkfreigabe nicht bestätigt. Die LAN-Einrichtung wurde in diesem Lauf daher
nicht erfolgreich abgeschlossen. Die späteren Reparaturversuche scheiterten an
der hier korrigierten erneuten Vollplatzforderung. Der Nachweis ist als
`evidence/windows-user-verification-2026-11-04.json` zusammengefasst; es handelt
sich um das Benutzerprotokoll, keine eigene Windows-Ausführung des Build-Agenten.


Version **1.8** ergänzt drei Gemma-4-Modelle zusätzlich zu allen drei bisherigen
Qwen-Modellen. Downloadquellen, Revisionen, Größen und SHA256 sind fest
hinterlegt; die öffentlichen Hugging-Face-Metadaten wurden erneut geprüft.
Alle drei Gemma-Dateien waren bei dieser Prüfung ohne HF-Zugriffssperre
verfügbar; für pyannote wird der sichtbare Read-Token weiterhin benötigt.
Die nativen GGUF-Chatvorlagen unterstützen deaktiviertes Thinking mit dem
bereits gebundenen llama.cpp-Stand b9637 (aedb2a5).

Neue API-Modell-IDs: `gemma12_qat_q4`, `gemma12_q8`, `gemma26_qat_q4`.
Diese erscheinen mit ihren lesbaren Modellnamen unter `/v1/models` und in
der Commander-Statusanzeige. Explizite Gemma-Anfragen haben keinen stillen
Fallback auf ein anderes Modell. Modellarchiv, SSD-/Netzquellen und gespeicherte
Prüfnachweise verwenden die vorhandenen Verfahren.
Ein Windows-GPU-Durchlauf und neue Leistungsmessungen wurden beim Bau dieser
Ausgabe nicht durchgeführt.

Version **1.7** behebt den Abbruch „Die Eigenschaft SelectedItem wurde für
dieses Objekt nicht gefunden“ beim Übernehmen vorhandener Einstellungen aus
1.4/1.5. Eine Datenvariable namens `$default` überschrieb beim Skriptstart das
ComboBox-Steuerelement `$script:Default`, weil PowerShell nicht zwischen Groß-
und Kleinschreibung unterscheidet. Die Datenvariable hat nun einen eindeutigen
Namen. Ein Test führt die tatsächlichen Startanweisungen auf Skriptebene aus,
prüft den Erhalt des Auswahlfelds und die anschließende SelectedItem-Abfrage.
Mit dem entpackten Assistenten aus der veröffentlichten EXE 1.6 wird derselbe
Fehler reproduziert; die korrigierte Fassung besteht sechs Übernahmefälle.
Die Windows-Oberfläche selbst wurde dabei nicht ausgeführt.

Version **1.6** trennt das parallel vorgehaltene Modell vom Anfrage-Standard.
Eine eigene Auswahl erlaubt ein geeignetes installiertes Modell oder keines.
Die Auswahl bleibt beim erneuten Öffnen des Assistenten erhalten. Alte
Konfigurationen werden beim Übernehmen anhand ihres bisherigen Standardprofils
vorbelegt; ein serielles bisheriges Standardmodell führt zu keiner Vorhaltung.

`GET /v1/runtime/status` meldet weiterhin unter `loaded.llm`, was tatsächlich
geladen ist. Zusätzlich enthält die Antwort `resident_quality` für das
konfigurierte Parallelmodell, `loaded_llm_label` für den Modellnamen und
`loaded_llm_mode` für die tatsächliche Betriebsart. `GET /v1/models` und
`/v1/runtime/profiles` liefern je Eintrag außerdem `resident`, `loaded`, `default`
und `serial_available`. Beide Abfragen verwenden den Commander-Zugangstoken.
Der Client wird durch dieses Serverpaket nicht verändert.

Version **1.5** korrigiert die LAN-Freigabe bei öffentlichem Windows-Netzwerkprofil.
Auf dem Testrechner waren die Portweiterleitung und `/health` auf localhost
funktionsfähig, Ethernet aber als `Public` eingestuft. Die Regel aus 1.4 galt nur
für `Private,Domain`. Die Regel wird jetzt mit `Profile Any` und ausdrücklich
aktiviert angelegt; ihre Einschränkungen auf die ausgewählte IP, TCP 8185 und
`LocalSubnet` bleiben bestehen. Der administrative Installationsschritt übernimmt
dies automatisch. Anschließend wird die aktive Regel aus `ActiveStore` ausgelesen.
Die Prüfung vom Serverrechner wird im Protokoll als lokaler Test gekennzeichnet.

Für eine bereits installierte 1.4 ist die unmittelbare Korrektur in einer
**als Administrator geöffneten Windows-PowerShell** möglich:

```powershell
Set-NetFirewallRule -Name "kienzledoku-server-8185" -Profile Any
```

Ein Arbeitsverzeichnis `C:\Windows\system32` bedeutet nicht, dass die Konsole
erhöhte Rechte besitzt. „Windows System Error 5 / Zugriff verweigert“ beim
Ändern der Regel verlangt zuerst ein tatsächlich erhöhtes PowerShell-Fenster.

Version **1.4** hält das Installationsprotokoll auch auf der Ergebnisseite
sichtbar, bis der Assistent ausdrücklich geschlossen wird. „Ganzes Protokoll
öffnen“ zeigt die vollständige Datei. Pro Lauf bleiben zusätzliche Dateien
`engine-<Laufkennung>.stderr.log` und `.stdout.log` im Windows-Zustandsordner
`%LOCALAPPDATA%\kienzledoku-server` erhalten. `last-operation.json` verweist auf
diese Dateien. Der HF-Token wird in der angezeigten Fehlermeldung ausgelassen;
die zusätzlichen Prozessdateien erhalten dieselben privaten Zugriffsrechte wie
die Konfigurationsdateien.

Endet der Hintergrundprozess ohne Abschlussstatus, zeigt der Assistent nun
Exitcode (dezimal und hexadezimal), letzten Schritt und vorhandene Prozessausgaben.
`native-process.json` enthält den letzten externen Prozessaufruf. Erkannte
Programmfehler enthalten zusätzlich die letzten Programmausgaben. In WSL wird
bei Python-Fehlern `installation-error.json` mit Schritt, Befehl und Traceback
abgelegt. Ein unveränderter Fortschrittswert gilt nicht als Nachweis, dass ein
bereits beendeter Prozess noch läuft. Die Ursache des gemeldeten Abbruchs von
1.3 ist mit dem vorhandenen Protokoll noch nicht nachgewiesen.

Außerdem speichert 1.4 erfolgreiche Integritätsprüfungen von unveränderten
Modellen unter Windows und WSL. Die gespeicherten Nachweise gelten auch für
Whisper- und pyannote-Dateien. Die Abschlussprüfung der tatsächlichen Inferenz
ist davon unabhängig und bleibt auswählbar.

Version **1.3** korrigiert die eigentliche Ursache der wiederholten WSL-Abbrüche:
Die bisherige Prozessroutine setzte alle Argumente in Anführungszeichen.
Der WSL-Parser vergleicht Verwaltungsschalter jedoch als rohe Tokens; dadurch
wurde `"--version"` als Linux-Befehl behandelt und „keine installierten
Distributionen“ gemeldet. Nun werden nur leere Argumente und Werte mit Leerraum
oder Anführungszeichen geschützt. Schalter wie `--version`, `--import` und
`--distribution` bleiben unverändert. Pfade mit Leerzeichen bleiben geschützt.

Ein zusätzlicher Test kompiliert den unveränderten Funktionskörper von Microsofts
`ParseArgument` in einer portablen Testumgebung. Er reproduziert das vorherige
Fehlverhalten und prüft die tatsächlich erzeugten neuen Kommandozeilen. Das ist
eine Parserprüfung unter Linux, kein vollständiger Windows-/WSL-Test.
Quellen: [helpers.cpp](https://github.com/microsoft/WSL/blob/master/src/windows/common/helpers.cpp),
[WslClient.cpp](https://github.com/microsoft/WSL/blob/master/src/windows/common/WslClient.cpp).

WSL wird außerdem über den expliziten Windows-Systempfad aufgerufen. Die
Verwaltungsaufrufe und Installerversion stehen jetzt im Protokoll, damit eine
abweichende Befehlsübergabe oder veraltete Startverknüpfung sofort erkennbar ist.

Die WSL-Einrichtung prüft nach dem Bootstrap zusätzlich die erfolgreiche
WSL-Versionsausgabe; bereits vorhandenes WSL wird nicht erneut installiert.
Windows-Komponenten im Zustand „Neustart ausstehend“ lösen einen Neustarthinweis
aus. WSL-Verwaltungsausgaben werden als UTF-16LE gelesen; Linux-Programmausgaben
bleiben UTF-8. Ein benötigter Neustart ist ein eigener Status im Assistenten.
Neun gezielte Regressionstests bilden diese Abläufe mit simulierten Windows-
Antworten nach; die Zeichendekodierung wird mit einem echten lokalen Prozess geprüft.

Version **1.1** behebt den Abbruch mit „SeSecurityPrivilege“ beim Schützen der
Konfigurations- und Tokendateien. Statt `Set-Acl` schreibt die Routine nur die
geänderten Dateizugriffsrechte über die .NET-Dateischnittstelle. Eigentümer,
Gruppe und Auditregeln werden nicht angefasst. Lesen dürfen weiterhin nur
der aufrufende Benutzer, SYSTEM und Administratoren; das Ergebnis wird anhand
der tatsächlichen Dateizugriffsrechte überprüft. Für diesen Schritt sind keine
Administrator- oder Audit-Sonderrechte vorgesehen. Die WSL- und LAN-Einrichtung
fordert erforderliche Administratorrechte weiterhin gesondert an.

Die Korrektur aus Version 1.0.1 ist enthalten: Der Abbruch mit „ExpectedBytes /
System.Object[]“ unter Windows PowerShell 5.1 ist behoben. JSON-Modelllisten werden
ausdrücklich in einzelne Dateieinträge aufgelöst. Dies korrigiert auch die Audio-Bestandsanzeige und die
Berechnung benötigter Dateigrößen. Ein gezielter Test bildet das abweichende
5.1-Verhalten nach und reproduziert vor der Korrektur denselben Fehler.
Weitere Fehlerprotokolle enthalten außerdem Fehlerkennung und Skript-Aufrufstelle.

Zum Fortsetzen nach diesen Fehlern die **neue EXE 1.12** öffnen und dasselbe
Modellarchiv auswählen. Keine Deinstallation und kein Löschen der Modelle nötig.
Ein alter Startmenüeintrag kann noch die bisherigen Skripte starten; die neue EXE
aktualisiert sie bei „Server installieren/reparieren“.
Im Fenstertitel und in der Kopfzeile muss **1.12** stehen.

Lokal geprüft: Python-Serverregressionen, beide Betriebsarten, Rückkehr nach
Modellwechsel, Authentifizierung, Worker-Sockets, Integritätsprüfung, WSL-
Konfiguration, PowerShell-Syntax und realer kleiner HTTPS-Download mit Teildatei.
Die EXE wird mit NSIS auf Linux gebaut und anschließend entpackt auf Vollständigkeit
kontrolliert. Es wird beim Erstellen kein produktiver KI-Server installiert.

**Für 1.12 noch nicht ausgeführt:** Start der Windows-Oberfläche und praktische
Wiederaufnahme mit realer WSL-Platzprüfung, den neuen Modelloptionen,
Bereinigung, UAC, Firewall und Autostart.
Die Korrekturen wurden mit lokalen Dateiprüfungen und simulierten Windows-/WSL-
Antworten geprüft. Der erfolgreiche Benutzerlauf aus 1.8 ersetzt diese Prüfung
der neuen Windows-Steuerung nicht. Nicht alle Windows-Versionen sind praktisch geprüft.

Die integrierte Abschlussprüfung verarbeitet synthetische Sprache durch ASR,
Sprechertrennung und jedes ausgewählte LLM, prüft Rückkehr und Objektidentität,
Tokenpflicht sowie langen Kontext. Ein stiller Modellfallback gilt dabei als
Fehler. Bei abgewählter Abschlussprüfung wird keine erfolgreiche Inferenzprüfung
behauptet. Protokolle und Ergebnisse befinden sich unter
`%LOCALAPPDATA%\kienzledoku-server` und in WSL unter `/var/lib/kienzledoku-server`.

## Quellen und Build

Die zentrale Datei `VERSION` bestimmt EXE-/ZIP-Namen, Assistent und
Installationsnachweise. Benutzerfestlegung für weitere veröffentlichte Änderungen:
laufende Unterversionen: nach **1.12** zunächst **1.13**, dann 1.14 usw.

`models.json`, `audio-files.json` und `ubuntu.json` enthalten feste Quellen,
Revisionen, Größen und Prüfsummen. Quellenherkunft: `evidence/source-provenance.json`.
Der Server basiert auf dem bestehenden lokalen Kienzledoku-Installer; Änderungen
für WSL, getrennte Paketierung und residenten Betrieb liegen ausschließlich hier.

Build mit Python 3 und NSIS 3:

```bash
python3 build/build.py --makensis /PFAD/ZU/makensis
```

Tests:

```bash
PYTHONPATH=linux/runtime:linux:tests python3 -m unittest discover -s tests -v
pwsh -NoProfile -File tests/test_core.ps1
pwsh -NoProfile -File tests/test_core.ps1 -Network
pwsh -NoProfile -File tests/test_json_compat.ps1
pwsh -NoProfile -File tests/test_wsl_bootstrap.ps1
pwsh -NoProfile -File tests/test_wizard_arguments.ps1
pwsh -NoProfile -File tests/test_wizard_migration.ps1
pwsh -NoProfile -File tests/test_model_options.ps1
pwsh -NoProfile -File tests/test_admin_retry.ps1
pwsh -NoProfile -File tests/test_private_files.ps1
python3 build/test_wsl_parser.py --pwsh /PFAD/ZU/pwsh
```

Die endgültige Windows-Prüfung muss mit Windows PowerShell 5.1 und realer NVIDIA-
GPU erfolgen. PowerShell 7 unter Linux prüft hier die übertragbaren Kernfunktionen
und Syntax, ersetzt aber keine Windows-Ausführung.
Der zusätzliche Parsercheck benötigt Python 3, PowerShell und einen C++17-Compiler
(`g++`) auf dem Buildrechner; diese Werkzeuge sind keine Windows-Installationsvoraussetzung.
`test_private_files.ps1` prüft echte Dateiberechtigungen ausschließlich unter
Windows. Unter Linux meldet es ausdrücklich SKIP und zählt nicht als bestanden.
Unter Windows PowerShell 5.1 kann es mit `powershell.exe -NoProfile -File
tests\test_private_files.ps1 -RequireWindows` ohne Administratorrechte ausgeführt werden.
