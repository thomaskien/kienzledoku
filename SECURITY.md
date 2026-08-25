# Sicherheit

## Unterstützte Version

| Version | Sicherheitsupdates |
| --- | --- |
| 1.2 | Ja |
| älter als 1.2 | Nein |

Kienzledoku 1.2 ist ein Entwicklungs- und Integrationsstand. Die bekannten
Einsatzgrenzen sind im Abschnitt
[Sicherheitsgrenzen](README.md#sicherheitsgrenzen) der README beschrieben.

## Schwachstellen vertraulich melden

Bitte Sicherheitsprobleme **nicht** in einem öffentlichen Issue melden. Nutzen
Sie nach Veröffentlichung die private Schwachstellenmeldung im Bereich
`Security` des GitHub-Repositorys. Falls dieser Meldeweg noch nicht aktiviert
ist, kontaktieren Sie den Repository-Betreiber zunächst privat und ohne
technische Details in einem öffentlichen Kanal.

Eine hilfreiche Meldung enthält:

- betroffene Version und macOS-Version;
- nachvollziehbare Schritte oder einen minimalen Testfall;
- erwartetes und tatsächliches Verhalten;
- mögliche Auswirkungen;
- vorgeschlagene Abhilfe, falls vorhanden.

Keine echten Patienten-, OAuth-, API-Schlüssel-, FHIR- oder Praxisnetzdaten
übermitteln. Ersetzen Sie sensible Werte durch eindeutig erkennbare
Platzhalter. Laden Sie keine Originalaufnahmen, Transkripte oder unbereinigten
Diagnoseprotokolle hoch.

## Besonders sensible Bereiche

Bei Änderungen an folgenden Komponenten ist eine zusätzliche Prüfung nötig:

- Deep-Link-Verarbeitung und OAuth-Token;
- FHIR-Zielvalidierung, TLS-Konfiguration und HTTP-Header;
- macOS-Schlüsselbund und API-Schlüssel;
- lokaler HTTP-Server und nativer WebKit-Container;
- temporäre Audio-, Transkript- und LLM-Dateien;
- Local-AI-Listen-Adresse, LaunchAgents und nicht authentifizierte Dienst-APIs;
- festgeschriebene Modellrevisionen, Größen und Prüfsummen;
- Linux-systemd-Dienste, ASR-Backend-Freigabe und Firewallregeln;
- LLM-JSON-Validierung und atomare FHIR-Transaktion;
- Protokollierung und Fehlermeldungen.

## Veröffentlichung eines Fixes

Sicherheitskorrekturen sollen zunächst vertraulich vorbereitet, mit den
netzwerkfreien Tests und einem kontrollierten Integrationstest geprüft und erst
danach gemeinsam mit einer klaren Versionsangabe veröffentlicht werden. Eine
Meldung darf erst öffentlich werden, wenn betroffene Betreiber aktualisieren
können.
