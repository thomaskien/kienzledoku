#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
exec "$SCRIPT_DIR/local-ai-macos/manager_macos.sh" \
    --action install --add-components llm "$@"
