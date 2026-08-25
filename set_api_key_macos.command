#!/bin/bash
set -e
SERVICE="Kienzledoku-T2med-API-Key"
printf "Eigenen T2med API-Key eingeben (Eingabe bleibt unsichtbar): "
IFS= read -r -s KEY
echo
if [ -z "$KEY" ]; then
  echo "Abgebrochen: leerer Key."
  exit 1
fi
/usr/bin/security add-generic-password -U -a "$USER" -s "$SERVICE" -w "$KEY" >/dev/null
echo "T2med-API-Key wurde für Kienzledoku im macOS-Schlüsselbund gespeichert."
