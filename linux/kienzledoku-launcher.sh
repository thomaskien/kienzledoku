#!/bin/bash
set -u

PYTHON3=@PYTHON3@
DATA_DIR=@DATA_DIR@
LOG_PATH=@LOG_PATH@

mkdir -p "$(dirname -- "$LOG_PATH")"
touch "$LOG_PATH"
chmod 600 "$LOG_PATH"
if [ "$#" -eq 0 ]; then
    exec "$PYTHON3" "$DATA_DIR/kienzledoku.py" --settings >>"$LOG_PATH" 2>&1
fi
[ "$#" -eq 1 ] || exit 2
case "$1" in
    kienzledoku://record*) runner=connect ;;
    kienzledoku-record://record*|t2demo:*|T2demo:*|whisperdoku:*|Whisperdoku:*) runner=direct ;;
    *) echo 'Ungültiger Record-Aufruf' >&2; exit 2 ;;
esac
deep_link="$1"
set --
shopt -s lastpipe
if [ "$runner" = connect ]; then
    export KIENZLEDOKU_PYTHON="$PYTHON3"
    printf '%s' "$deep_link" | exec "$DATA_DIR/kienzleconnect" --deep-link-stdin >>"$LOG_PATH" 2>&1
else
    printf '%s' "$deep_link" | exec "$PYTHON3" "$DATA_DIR/kienzledoku.py" --deep-link-stdin >>"$LOG_PATH" 2>&1
fi
