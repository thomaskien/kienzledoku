#!/bin/bash
set -u

PYTHON3=@PYTHON3@
DATA_DIR=@DATA_DIR@
LOG_PATH=@LOG_PATH@

# The desktop specification supplies the complete URI as one argument. Bash's
# lastpipe mode lets the Python process replace this launcher while receiving
# the URI from an anonymous pipe. The long-running process command line
# therefore contains no OAuth material, and nothing is written to disk.
if [ "$#" -ne 1 ]; then
    echo "FEHLER: Kienzledoku wird aus T2med über kienzledoku:// gestartet." >&2
    exit 2
fi
case "$1" in
    kienzledoku:*|Kienzledoku:*|t2demo:*|T2demo:*|whisperdoku:*|Whisperdoku:*) ;;
    *) echo "FEHLER: Ungültiges Kienzledoku-URL-Schema." >&2; exit 2 ;;
esac
mkdir -p "$(dirname -- "$LOG_PATH")"
touch "$LOG_PATH"
chmod 600 "$LOG_PATH"

deep_link="$1"
set --
shopt -s lastpipe
printf '%s' "$deep_link" | exec "$PYTHON3" \
    "$DATA_DIR/kienzledoku.py" \
    --deep-link-stdin \
    >> "$LOG_PATH" 2>&1
