# Lokale Audiosteuerung ab 1.6

VAD und Stilleschwelle werden im Benutzerprofil dieses Clients in den technischen
`record`-Einträgen `vad_enabled` und `silence_threshold_dbfs` von `config.toml`
gespeichert. Neue Fenster übernehmen sie; andere offene Fenster behalten ihre
Objekte. Erstinstallation: VAD an, −50 dBFS. Keine Patienten- oder Audiopersistenz.

Der Eingang wird vor dem Gate gemessen (RMS/dBFS). 20-ms-Gateframes mit 200 ms
Vorschau, 300 ms Nachlauf und kurzen Übergängen erhalten die Samplezahl exakt.
Der Slider wirkt auf kommende Frames; VAD wird je beginnendem ASR-Block festgehalten.
VAD aus lässt das Pegel-Gate aktiv. Digitales Nullaudio wird auch ohne VAD übersprungen.

Ab 1.7.5 liegt der transparente Schwellengriff direkt über dem Live-Pegel;
Pegel und Griff verwenden dieselbe dBFS-Skala. Der Griff hat keine Füllung,
die den Ausschlag verdeckt. Tastaturbedienung und Client-Speicherung bleiben erhalten.

Die zusätzliche adaptive RMS-Schwelle der Blocksteuerung entfällt ab 1.7.5.
Pausen werden ausschließlich am Nullsignal nach dem Pegel-Gate erkannt.
Jeder logische Kernblock wird nach höchstens 20 Sekunden plus einem 30-ms-Frame
begrenzt, auch bei Stille oder leiser Sprache. Hinzu kommen bis zu 700 ms
Nachkontext und 200 ms Gate-Vorschau vor dem Senden; Warteschlange, Laden und
ASR-Laufzeit sind nicht Teil dieser Blockgrenze. Anschließend überspringt VAD
Nichtsprachabschnitte. Es entstehen dadurch keine zusätzlichen Whisper-Aufrufe
für reine Stille. Alte RMS-Kommandozeilenoptionen werden nur noch angenommen,
beeinflussen die Blockbildung aber nicht mehr.

Silero v6 läuft lokal auf CPU, ONNX Runtime 1.19.2, NumPy 1.26.4. Die geringe
zusätzliche Client-Laufzeit benötigt keine GPU und keinen Commander-Schalter.
Standardwerte: Sprachwahrscheinlichkeit 0,5, keine Mindestsprachdauer, 2 s
Trennpause, 400 ms Rand je Sprachfenster. Fenster werden einzeln transkribiert;
Originaloffsets werden vor der bestehenden Wort-Kernzuordnung wieder addiert.
Originalaudio für Sprechertrennung bleibt unverändert im RAM.

Quelle des Modells: faster-whisper v1.2.1, `faster_whisper/assets/silero_vad_v6.onnx`.
SHA256: `4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2`.
Der Timestamp-Detektor und ONNX-Aufruf sind aus derselben Version übernommen;
kein Concatenate-/collect_chunks-Pfad. MIT-Lizenzen: `assets/silero-vad-LICENSE.txt`.
Alle Abhängigkeiten für Mac/Windows sind im Paket; Linux installiert die festgelegten
Versionen bei der Installation. Kein Modell-Download beim Patientenaufruf.

VAD ist eine statistische Spracherkennung, kein Garant gegen jeden Störlaut.
Leise Sprache erfordert eine passende Stilleschwelle. Ein Ausführungsfehler wird
angezeigt; der Detektor wird nicht heimlich abgeschaltet.
