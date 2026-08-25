#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
LOCAL_AI_CONFIG="$HOME/Library/Application Support/Kienzledoku Local AI/listen-address"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    printf '%s\n' \
        "Kienzledoku vollständig lokal installieren" \
        "" \
        "Zuerst werden die Local-AI-Optionen verarbeitet; danach wird die App" \
        "auf die gewählte lokale Listen-Adresse und die Standardports eingerichtet." \
        "" \
        "Optionen entsprechen: ./install_local_ai_macos.command --help"
    exit 0
fi

echo "=== 1/2: Lokale KI-Dienste installieren ==="
if [ "$#" -eq 0 ]; then
    "$SCRIPT_DIR/install_local_ai_macos.command" --components all
else
    "$SCRIPT_DIR/install_local_ai_macos.command" "$@"
fi

echo
echo "=== 2/2: Kienzledoku-App installieren ==="

LOCAL_AI_HOST="127.0.0.1"
if [ -f "$LOCAL_AI_CONFIG" ]; then
    SAVED_HOST="$(/usr/bin/tr -d '[:space:]' < "$LOCAL_AI_CONFIG")"
    if [[ "$SAVED_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        LOCAL_AI_HOST="$SAVED_HOST"
    fi
fi
if [ "$LOCAL_AI_HOST" = "0.0.0.0" ]; then
    LOCAL_AI_HOST="127.0.0.1"
fi

export KIENZLEDOKU_INSTALL_ASR_HOST="$LOCAL_AI_HOST"
export KIENZLEDOKU_INSTALL_ASR_PORT="8179"
export KIENZLEDOKU_INSTALL_DIARIZATION_HOST="$LOCAL_AI_HOST"
export KIENZLEDOKU_INSTALL_DIARIZATION_PORT="8183"
export KIENZLEDOKU_INSTALL_LLM_HOST="$LOCAL_AI_HOST"
export KIENZLEDOKU_INSTALL_LLM_PORT="8080"

exec "$SCRIPT_DIR/install_macos.command"
