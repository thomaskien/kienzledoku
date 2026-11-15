# kienzledoku 1.7.6 für Ubuntu 24.04 x86_64

Das Archiv entpacken, ein Terminal im entpackten Ordner öffnen und ausführen:

```sh
./install_linux.sh
```

Für **client** oder **both** als normaler, angemeldeter Desktop-Benutzer
starten. Nur der Server-Helfer fordert dann bei Bedarf Administratorrechte über
sudo an. Ein Root-Start ist ausschließlich für **server** erlaubt; dort wird
kein weiteres sudo verwendet. Client und Server können auf demselben Rechner
laufen.

Serverauswahl als normaler Benutzer (sudo wird nur für den geschützten
Server-Schritt aufgerufen):

```sh
./install_linux.sh --components server
```

In einer bereits geöffneten Root-Shell gilt derselbe Befehl; auch dort wird
kein sudo vorangestellt.

Client: GTK4/WebKitGTK, PortAudio, Python und Connect. Die benötigten Pakete und
eine eigene Python-Umgebung werden eingerichtet. Der Ubuntu-Schutz für
Benutzernamensräume bleibt erhalten; nur das native Aufnahmefenster erhält das
gezielte AppArmor-Profil. Die Aufnahme läuft ohne lokale Entwurfsablage.

Server: NVIDIA RTX 20 oder neuer, mindestens 8 GiB VRAM und 20 GiB RAM;
größere Modelle benötigen mehr Speicher. Ein funktionierender NVIDIA-Treiber
wird vorausgesetzt. Der Installer zeigt die passenden Modelle, erlaubt mehrere
Installationen und fragt aktive Stufen, Felder und Prompt ab. Der Prompt lässt
sich mit `$EDITOR` bearbeiten oder auf Standard setzen. Ein vorhandener
Hugging-Face-Token kann verdeckt wiederverwendet werden. Modelle werden mit den
hinterlegten Prüfsummen geprüft. Standardmäßig ist der Commander nur lokal
erreichbar und der Token-Schutz aus.

Whisper wird auf Anfrage geladen, vor LLM entladen und anschließend nicht
vorgeladen. Der Commander läuft als systemd-Dienst. Status:
`systemctl status kienzledoku-commander`.

T2med-Aktivierung: **Drittanbieter-Zugriffe verwalten → Per Produktcode aktivieren →
Produktcode `kienzledoku` eingeben und bestätigen**. Danach erscheint
**Dr. Thomas Kienzle - KienzleDoku** mit einem **grünen Statuspunkt**.
Das Linux-Paket 1.7.6 enthält den endgültigen Hersteller-Key in kompilierten
Binärdateien. Für die URL den aktivierten **KienzleDoku**-Eintrag verwenden.
Öffentliche Quellcode-Builds ohne privaten Build-Eingang verwenden weiterhin den Demo-Key. Die verlinkte GitHub-Anleitung zeigt alle Schritte mit Bildern.

Nach der Clienteinrichtung zeigt das Terminal die vollständige T2med-Adresse
zum Kopieren sowie die Drittanbieter-Anleitung:
[Einrichtung auf GitHub](https://github.com/thomaskien/kienzledoku#t2med-einrichten-und-verwenden).

`./install_linux.sh --self-test` prüft das Paket ohne Installation.
`./install_linux.sh --components both --plan` zeigt den vorgesehenen Umfang
ohne Systemänderungen. Der Plan ist auch als root rein beschreibend; eine echte
Clientinstallation als root bleibt gesperrt.

## Deinstallation

Der Textassistent kann Client, Server oder beide Komponenten gezielt entfernen:

```sh
./install_linux.sh --uninstall --components client
./install_linux.sh --uninstall --components server
./install_linux.sh --uninstall --components both
```

Client und **both** als angemeldeter Desktop-Benutzer starten. Bei **server**
fordert der Assistent bei Bedarf sudo an; in einer Root-Shell wird kein sudo
benötigt. Vor dem Löschen zeigt er eine Zusammenfassung und verlangt eine
Bestätigung. Heruntergeladene Kienzledoku-Modelle sowie technische Einstellungen
und Protokolle bleiben standardmäßig erhalten und werden nur nach getrennter
ausdrücklicher Auswahl gelöscht. Externe Modellarchive, Hugging-Face-Caches,
Treiber, Systempakete sowie gemeinsam verwendete GTK-/AppArmor-Helfer bleiben
unverändert.

Eine offene Aufnahme oder laufende Serverinstallation blockiert die
Deinstallation. Gleichnamige fremde Dienste und Dateien werden nicht entfernt;
bei unsicherer Zuordnung oder Symlinks bricht der Assistent vor Änderungen ab.

Ein vollständiger Desktop-/GPU-Installationslauf dieser Ausgabe steht aus. Ein
vorhandener produktiver Server wird durch das Bauen des Pakets nicht verändert;
der spätere Installer richtet seine systemd-Dienste ein.
