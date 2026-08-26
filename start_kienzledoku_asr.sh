#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Kienzledoku 1.2.1: Natural Pause -> Final-Block-ASR -> pyannote -> LLM ==="
echo "Verzeichnis: $SCRIPT_DIR"

# v6.2: Der Python-venv liegt absichtlich NICHT im (ggf. per iCloud
# synchronisierten) Projektverzeichnis. Python-venvs sind zwischen Macs,
# Python-Versionen und Architekturen nicht portabel.
find_python3() {
    python_is_supported() {
        "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
    }

    REQUESTED_PYTHON="${KIENZLEDOKU_PYTHON:-${WHISPERDOKU_PYTHON:-}}"
    if [ -n "$REQUESTED_PYTHON" ]; then
        if [ -x "$REQUESTED_PYTHON" ] && python_is_supported "$REQUESTED_PYTHON"; then
            printf '%s\n' "$REQUESTED_PYTHON"
            return 0
        fi
        if command -v "$REQUESTED_PYTHON" >/dev/null 2>&1; then
            candidate="$(command -v "$REQUESTED_PYTHON")"
            if python_is_supported "$candidate"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
        echo "FEHLER: KIENZLEDOKU_PYTHON benötigt eine ausführbare Python-Version >= 3.9: $REQUESTED_PYTHON" >&2
        return 1
    fi

    for candidate in \
        "$(command -v python3 2>/dev/null || true)" \
        /Library/Frameworks/Python.framework/Versions/3.9/bin/python3 \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3
    do
        if [ -n "$candidate" ] && [ -x "$candidate" ] && python_is_supported "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    echo "FEHLER: Python 3 nicht gefunden." >&2
    echo "Benötigt wird Python >= 3.9. Optional kann KIENZLEDOKU_PYTHON=/pfad/zu/python3 gesetzt werden." >&2
    return 1
}

BASE_PYTHON="$(find_python3)" || exit 1

if ! "$BASE_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    echo "FEHLER: Python >= 3.9 erforderlich: $BASE_PYTHON" >&2
    "$BASE_PYTHON" --version >&2 || true
    exit 1
fi

PY_MM="$("$BASE_PYTHON" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))')"
PY_TAG="$(printf '%s' "$PY_MM" | tr -d '.')"
ARCH="$(uname -m)"
VENV_ROOT="${KIENZLEDOKU_ASR_VENV_ROOT:-${WHISPERDOKU_VENV_ROOT:-$HOME/.kienzlefon-whisperdoku/venvs}}"
VENV_DIR="$VENV_ROOT/client-v6-${ARCH}-py${PY_TAG}"
VENV_PYTHON="$VENV_DIR/bin/python3"

# Ein defekter/alter machine-local venv wird sicher neu aufgebaut.
if [ -d "$VENV_DIR" ]; then
    if [ ! -x "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c 'import sys' >/dev/null 2>&1; then
        echo "Defekter lokaler venv erkannt, wird neu erstellt: $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    mkdir -p "$VENV_ROOT"
    echo "Erzeuge lokalen venv: $VENV_DIR"
    "$BASE_PYTHON" -m venv "$VENV_DIR"
fi

if [ ! -x "$VENV_PYTHON" ]; then
    echo "FEHLER: venv-Python fehlt nach Erstellung: $VENV_PYTHON" >&2
    exit 1
fi

VENV_MM="$("$VENV_PYTHON" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))')"
if [ "$VENV_MM" != "$PY_MM" ]; then
    echo "Python-Version des venv passt nicht ($VENV_MM statt $PY_MM), erstelle neu."
    rm -rf "$VENV_DIR"
    "$BASE_PYTHON" -m venv "$VENV_DIR"
fi

echo "Basis-Python: $($BASE_PYTHON --version 2>&1) | $BASE_PYTHON"
echo "Laufzeit:     $($VENV_PYTHON --version 2>&1) | $VENV_PYTHON"
echo "Architektur:  $ARCH"

# Ein ggf. aus einer älteren iCloud-Kopie vorhandenes ./venv wird absichtlich
# ignoriert. Es kann auf einem anderen Mac auf einen nicht vorhandenen
# Interpreter zeigen und ist nicht portabel.
if [ -d "$SCRIPT_DIR/venv" ]; then
    echo "Hinweis: vorhandenes ./venv wird absichtlich ignoriert (nicht portabel zwischen Macs)."
fi

# Für WAV-Replay und --help ist sounddevice nicht nötig. Beim Mikrofonbetrieb
# bzw. --list-devices installieren wir es im machine-local venv bei Bedarf.
NEED_SD=1
for arg in "$@"; do
    case "$arg" in
        --input-wav|--input-wav=*|--help|-h) NEED_SD=0 ;;
        --list-devices) NEED_SD=1 ;;
    esac
done

if [ "$NEED_SD" -eq 1 ]; then
    if ! "$VENV_PYTHON" -c 'import sounddevice' >/dev/null 2>&1; then
        echo "Installiere Client-Abhängigkeiten in $VENV_DIR ..."
        # Python 3.9 bleibt auf der auf Mojave bewährten pip-Linie.
        if [ "$PY_MM" = "3.9" ]; then
            "$VENV_PYTHON" -m pip install "pip<25"
        fi
        "$VENV_PYTHON" -m pip install -r requirements-asr-client.txt
    fi
fi

exec "$VENV_PYTHON" kienzledoku_asr_v6.py "$@"
