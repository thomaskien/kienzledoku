#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Aufruf: $0 SERVER WAV [LANGUAGE]" >&2
  exit 2
fi

SERVER="$1"
WAV="$2"
LANGUAGE="${3:-de}"
URL="http://${SERVER}:8179/v1/asr/final-block"

if [[ ! -f "$WAV" ]]; then
  echo "FEHLER: Datei nicht gefunden: $WAV" >&2
  exit 1
fi

if [[ -n "${WLK_API_TOKEN:-}" ]]; then
  curl -fsS \
    -H "Authorization: Bearer ${WLK_API_TOKEN}" \
    -X POST "$URL" \
    -F "file=@${WAV}" \
    -F "language=${LANGUAGE}"
else
  curl -fsS \
    -X POST "$URL" \
    -F "file=@${WAV}" \
    -F "language=${LANGUAGE}"
fi | python3 -m json.tool
