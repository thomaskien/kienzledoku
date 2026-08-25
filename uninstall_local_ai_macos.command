#!/bin/bash
set -e

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd -P)"
INSTALLED="$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh"

if [ -x "$INSTALLED" ]; then
    exec "$INSTALLED" --action uninstall "$@"
fi

exec "$SOURCE_DIR/local-ai-macos/manager_macos.sh" --action uninstall "$@"
