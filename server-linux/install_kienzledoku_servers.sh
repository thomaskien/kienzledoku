#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  echo "FEHLER: Als normaler Benutzer mit sudo-Berechtigung starten, nicht als root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

for argument in "$@"; do
  case "$argument" in
    -h|--help|--version|--self-test)
      exec "$SCRIPT_DIR/install_kienzlefon_ai_server.sh" "$argument"
      ;;
  esac
done

"$SCRIPT_DIR/install_kienzlefon_ai_server.sh" \
  --role llm \
  --role asr \
  --role pyannote \
  --asr-backend-bind 0.0.0.0 \
  "$@"

sudo "$SCRIPT_DIR/install_final_block_endpoint.sh"

echo
echo "Kienzledoku-Linux-Dienste installiert:"
echo "  LLM:          Port 8080"
echo "  Final-ASR:    Port 8179, /v1/asr/final-block"
echo "  Diarisierung: Port 8183"
echo "Port 8179 bindet für den entfernten Client an alle Schnittstellen."
echo "Den Zugriff jetzt per Firewall auf die IP des Kienzledoku-Macs begrenzen."
