#!/bin/bash
set -eu

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="$DATA_HOME/kienzledoku"
CONFIG_DIR="$CONFIG_HOME/kienzledoku"
LAUNCHER_PATH="$HOME/.local/bin/kienzledoku"
DESKTOP_PATH="$DATA_HOME/applications/kienzledoku.desktop"

rm -rf -- "$DATA_DIR"
rm -rf -- "$CONFIG_DIR"
rm -f -- "$LAUNCHER_PATH" "$DESKTOP_PATH"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications"
fi

echo "Kienzledoku wurde entfernt."
echo "Diagnoseprotokoll und ein eventuell gespeicherter API-Key bleiben absichtlich erhalten."
echo "Den API-Key entfernt ./use_demo_key_linux.sh."
