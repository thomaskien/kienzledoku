#!/bin/bash
set -e
MANAGER="$HOME/Library/Application Support/Kienzledoku Local AI/scripts/manager_macos.sh"
if [ ! -x "$MANAGER" ]; then
    echo "Kienzledoku Local AI ist noch nicht installiert."
    exit 1
fi
"$MANAGER" --action start
echo
echo "Die Modelle werden nacheinander geladen. Dieses Fenster kann geschlossen werden."
