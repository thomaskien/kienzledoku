#!/bin/bash
set -e
MANAGER="$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh"
if [ ! -x "$MANAGER" ]; then
    echo "Kienzledoku Local AI ist nicht installiert."
    exit 1
fi
exec "$MANAGER" --action stop
