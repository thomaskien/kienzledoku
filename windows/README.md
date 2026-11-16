# kienzledoku 1.8 für Windows x64

`kienzledoku-1.8-windows-x64-setup.exe` öffnen und **Client**, **Server** oder
**Client und Server** wählen. Die Vorbereitung wird sofort sichtbar angezeigt;
anschließend führt derselbe Wizard-Aufbau wie auf dem Mac durch Komponenten,
Verbindungen, Modelle, Dokumentation und Zusammenfassung. Erst danach beginnt
die Installation mit laufender Statusanzeige. Ein erforderlicher Windows-Neustart unterbricht den Ablauf;
danach dieselbe EXE erneut starten. Vorhandene Modellarchive werden wiederverwendet.

Client: Windows 10/11 x64, Mikrofon, Microsoft Edge WebView2 und Microsoft Visual C++
v14 Redistributable **x64** für die lokale Sprachaktivitätserkennung. Python, PortAudio,
Connect und das native Aufnahmefenster sind enthalten. Fehlt WebView2, lädt der
Installer den Microsoft-Installer und prüft dessen Signatur vor dem Start.
Fehlen die für VAD benötigten C++-Bibliotheken, installiert das Setup das signierte
Microsoft-Redistributable mit sichtbarer Statusmeldung und Administratorabfrage.
Anschließend prüft es die tatsächliche VAD-Ausführung, bevor eine Serverinstallation
oder ein Clientaustausch beginnt. Fehlermeldungen enthalten die ursprüngliche Ursache.
Ein erforderlicher Neustart wird ausdrücklich angezeigt. Die Python-Abhängigkeiten
werden beim Build einschließlich Windows-spezifischer Anforderungen geprüft.
Server: Windows 11 x64, WSL2, NVIDIA RTX 20 oder neuer mit mindestens 8 GiB VRAM,
ausreichend RAM und Speicherplatz. Die KI-Modelle werden nur nach Auswahl geladen.

Der Assistent verwendet das mit Windows gelieferte Windows PowerShell 5.1 und
WebView2 für die gemeinsame Oberfläche. Windows Forms zeigt die Vorbereitung
und den Startmenü-Deinstaller. Für den Client sind weder WSL noch eine NVIDIA-GPU erforderlich.
T2med und Commander müssen vom Client erreichbar sein. Internet wird für fehlende
WebView2-/Serverlaufzeiten und Modelldownloads benötigt; bei zugriffsbeschränkten
Modellen zusätzlich ein freigeschaltetes Hugging-Face-Konto mit Read-Token.
Die Serverinstallation benötigt aktivierte CPU-Virtualisierung, ein lokales
beschreibbares Laufwerk und Administratorrechte für die Windows-/WSL-Einrichtung;
ein Neustart kann erforderlich sein. RAM und Speicherbedarf hängen von der
Modellauswahl ab. Siehe auch [Microsofts WebView2-Systemunterstützung](https://learn.microsoft.com/en-us/microsoft-edge/webview2/#supported-platforms).

Im Modell- und Dokumentationsschritt lassen sich mehrere Modelle installieren, die aktiven
Stufen zuordnen, Dokumentationsfelder auswählen und der Commander-Prompt anzeigen,
bearbeiten oder auf Standard setzen. Token-Schutz ist standardmäßig aus.
Ein anderer Commander kann die LLM-Verarbeitung übernehmen. Whisper kann auf den
ersten Audioblock warten und bleibt nach der LLM-Verarbeitung entladen.

In T2med **Drittanbieter-Zugriffe verwalten → Per Produktcode aktivieren** öffnen,
als Produktcode **`kienzledoku`** eingeben und bestätigen. Danach erscheint
**Dr. Thomas Kienzle - KienzleDoku** mit einem **grünen Statuspunkt**. Der Installer zeigt diese Schritte auch als Bildanleitung. Die offizielle Ausgabe
1.8 enthält den endgültigen Hersteller-Key. Für die URL den aktivierten
**KienzleDoku**-Eintrag verwenden.

Die Clienteinrichtung fragt T2med, Commander und einen optionalen Commander-Token
ab. Alle KI-Dienste laufen verpflichtend über Commander; die Vorgabe für neue
externe Clients ist `http://10.0.83.140:8185`. Bestehende Adressen bleiben erhalten,
eine gemeinsame Installation verwendet den lokalen Commander. Am Ende erscheinen die kopierbare Drittanbieter-Adresse, die kurze Anleitung
und der Link zur vollständigen GitHub-Dokumentation. Technische Einstellungen
liegen unter `%LOCALAPPDATA%\kienzledoku record`; Aufnahmen und Entwürfe bleiben
im Arbeitsspeicher. Vor einer Aktualisierung offene Aufnahmen übernehmen oder
bewusst schließen. Das Setup beendet keine Aufnahme automatisch.

Der Installer ist nicht mit einem Windows-Herausgeberzertifikat signiert.
Das Paket wurde auf macOS für Windows gebaut und anschließend entpackt und auf
unveränderte Nutzlast geprüft. Ein tatsächlicher Windows-/WSL-/Mikrofontest dieser
Ausgabe steht aus.

Build: `installer/build_desktop.py --tools /Pfad/zum/geprüften/Toolcache`.
Die Versionen und SHA-256-Werte der Abhängigkeiten stehen in
`windows/runtime-lock.json`. Bestehende Ausgabedateien werden nicht überschrieben.
Der bisherige MSVC-/Inno-Build unter `windows/build.ps1` bleibt für den separaten
Client verfügbar.

## Fortsetzen nach dem Abschlussfehler in 1.7.2

Seit 1.7.3 korrigiert ist der Abbruch mit „Complete-CodeUpdate wurde nicht erkannt“.
Den neuen Installer im selben Windows-Konto öffnen und die bisherigen Komponenten
wählen. Vorhandene Konfiguration und geprüfte Modelle werden übernommen. Eine
vorherige Löschung der WSL-Umgebung ist für diese Korrektur nicht nötig.

Promptvorlagen werden ausdrücklich als UTF-8 gelesen. Ein exakt erkannter,
fehlerhaft eingelesener Standardprompt aus 1.7.2 wird korrekt vorbelegt und bei der
Serverinstallation gespeichert; individuell angepasste Prompts bleiben erhalten.
Bei einem individuell angepassten Prompt mit falschen Zeichen kann der Text im
Wizard korrigiert oder bewusst über den Standardknopf ersetzt werden.

## Deinstallieren

Im Setup **Deinstallieren** wählen oder **kienzledoku deinstallieren** im Startmenü
öffnen. Client und Server sind getrennt wählbar. Modelle und technische
Einstellungen werden nur nach ausdrücklicher Auswahl entfernt. Ohne Entfernen
der Modelle bleibt die deaktivierte eigene WSL-Umgebung erhalten; Downloadarchive
und andere WSL-Umgebungen bleiben erhalten. Offene Record-Fenster zuerst schließen.
Mit **Servermodelle und eigene Kienzledoku-WSL-Umgebung entfernen** wird die
Distribution `kienzledoku-server` einschließlich ihrer virtuellen Festplatte
gelöscht. Windows' WSL-Funktion und andere Distributionen werden nicht deinstalliert.

Sprechertrennung: immer geladen, mit Whisper oder seriell. Aufnahmeabschnitte
enden nach maximal zwei Stunden kontrolliert; anschließend ist Fortsetzen möglich.
