#!/bin/bash
set -eu

if ! command -v secret-tool >/dev/null 2>&1; then
    echo "FEHLER: secret-tool fehlt. Unter Ubuntu 24.04: sudo apt install libsecret-tools" >&2
    exit 1
fi
printf "Eigenen T2med API-Key eingeben (Eingabe bleibt unsichtbar): "
IFS= read -r -s KEY
echo
if [ -z "$KEY" ]; then
    echo "Abgebrochen: leerer Key."
    exit 1
fi
printf '%s' "$KEY" | secret-tool store \
    --label="Kienzledoku T2med API-Key" \
    application kienzledoku \
    service t2med-api-key
unset KEY
echo "T2med-API-Key wurde im Linux-Schlüsselbund (Secret Service) gespeichert."
