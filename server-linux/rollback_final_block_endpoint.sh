#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "FEHLER: Bitte als root ausführen." >&2
  exit 1
fi

SERVICE=kienzlefon-ai-asr-backend.service
LAST=/root/kienzlefon-final-block-v6-server-LAST

PY=""
for candidate in \
  /opt/kienzlefon-ai-v2/python/asr-venv/bin/python \
  /opt/kienzlefon-ai/python/asr-venv/bin/python
do
  if [[ -x "$candidate" ]]; then
    PY="$candidate"
    break
  fi
done

if [[ -z "$PY" ]]; then
  echo "FEHLER: ASR-Python weder im v2- noch im Legacy-Pfad gefunden." >&2
  exit 1
fi

if [[ ! -f "$LAST" ]]; then
  echo "FEHLER: Kein LAST-Pointer gefunden: $LAST" >&2
  exit 1
fi

BACKUP_DIR="$(cat "$LAST")"
BACKUP="$BACKUP_DIR/basic_server.py"

if [[ ! -f "$BACKUP" ]]; then
  echo "FEHLER: Backup fehlt: $BACKUP" >&2
  exit 1
fi

WLK_DIR="$($PY - <<'PY'
import pathlib
import whisperlivekit
print(pathlib.Path(whisperlivekit.__file__).resolve().parent)
PY
)"
TARGET="$WLK_DIR/basic_server.py"

cp -a "$BACKUP" "$TARGET"
"$PY" -m py_compile "$TARGET"
systemctl restart "$SERVICE"
sleep 4
systemctl --no-pager --full status "$SERVICE"
echo "ROLLBACK_OK: $BACKUP -> $TARGET"
