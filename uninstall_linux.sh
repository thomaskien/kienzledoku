#!/bin/bash
set -eu

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="$DATA_HOME/kienzledoku"
CONFIG_DIR="$CONFIG_HOME/kienzledoku"
LAUNCHER_PATH="$HOME/.local/bin/kienzledoku"
DESKTOP_PATH="$DATA_HOME/applications/kienzledoku.desktop"
SYSTEM_HELPER_DIR="/usr/local/libexec/kienzledoku"
SYSTEM_HELPER_PATH="$SYSTEM_HELPER_DIR/kienzledoku_window_linux"
APPARMOR_PROFILE_PATH="/etc/apparmor.d/kienzledoku-window"

if [ -f "$APPARMOR_PROFILE_PATH" ] || [ -e "$SYSTEM_HELPER_PATH" ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "FEHLER: sudo wird zum Entfernen des geschützten Linux-Fensters benötigt." >&2
        exit 1
    fi
    if [ -f "$APPARMOR_PROFILE_PATH" ]; then
        sudo apparmor_parser -R "$APPARMOR_PROFILE_PATH" >/dev/null 2>&1 || true
        sudo rm -f -- "$APPARMOR_PROFILE_PATH"
    fi
    sudo rm -f -- "$SYSTEM_HELPER_PATH"
    sudo rmdir "$SYSTEM_HELPER_DIR" >/dev/null 2>&1 || true
fi

rm -rf -- "$DATA_DIR"
rm -rf -- "$CONFIG_DIR"
rm -f -- "$LAUNCHER_PATH" "$DESKTOP_PATH"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications"
fi

echo "Kienzledoku wurde entfernt."
echo "Diagnoseprotokoll und ein eventuell gespeicherter API-Key bleiben absichtlich erhalten."
echo "Den API-Key entfernt ./use_demo_key_linux.sh."
