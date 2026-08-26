#!/bin/bash
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/native/KienzledokuWindowLinux.c"
OUTPUT="${1:-$SCRIPT_DIR/kienzledoku_window_linux}"

if ! command -v pkg-config >/dev/null 2>&1; then
    echo "FEHLER: pkg-config fehlt." >&2
    exit 1
fi
if ! pkg-config --exists gtk4 webkitgtk-6.0; then
    echo "FEHLER: GTK 4/WebKitGTK 6.0 Entwicklungsdateien fehlen." >&2
    echo "Unter Ubuntu 24.04: sudo apt install build-essential pkg-config libgtk-4-dev libwebkitgtk-6.0-dev" >&2
    exit 1
fi

cc -std=c11 -O2 -Wall -Wextra -Werror \
    "$SOURCE" \
    -o "$OUTPUT" \
    $(pkg-config --cflags --libs gtk4 webkitgtk-6.0)
chmod 700 "$OUTPUT"
echo "Linux-WebKitGTK-Fenster gebaut: $OUTPUT"
