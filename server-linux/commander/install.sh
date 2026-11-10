#!/usr/bin/env bash
# Absichtlich kein Modell-Download, keine Treiber-/venv-Änderung.
set -euo pipefail
ACTION=${1:---help}
case "$ACTION" in
  --check|--install|--activate|--rollback) ;;
  *) echo 'Aufruf: sudo ./install.sh --check|--install|--activate|--rollback'; exit 0 ;;
esac
[[ ${EUID:-$(id -u)} == 0 ]] || { echo 'Bitte als root ausführen.' >&2; exit 1; }
SOURCE=$(cd "$(dirname "$0")/../.." && pwd -P)
PREFIX=/opt/kienzledoku-commander
CONFIG=/etc/kienzledoku-commander
STATE=/var/lib/kienzledoku-commander
BACKUP=$STATE/worker-backup
ASR=kienzlefon-ai-asr-backend.service
DIAR=kienzlefon-ai-diarization.service
LLM=kienzlefon-ai-llm.service
UNIT=kienzledoku-commander.service
PY=/usr/bin/python3
"$PY" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ erforderlich"'
# token.env contains only KEY=value entries; never execute it as shell code.
if [[ -f "$CONFIG/token.env" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^(KIENZLEDOKU_COMMANDER_TOKEN|KIENZLEDOKU_COMMANDER_ASR_TOKEN)=[A-Za-z0-9_-]+$ ]] || { echo 'Ungültige token.env (nur unquotierte Tokens aus A-Z/a-z/0-9/_/-).' >&2; exit 1; }
    export "$line"
  done < "$CONFIG/token.env"
fi

rollback() {
  systemctl stop "$UNIT" || true
  PYTHONPATH="$SOURCE" "$PY" -m kienzledoku_commander.patch_workers --backup "$BACKUP" --rollback
  rm -f "/etc/systemd/system/$ASR.d/90-kienzledoku-commander.conf" "/etc/systemd/system/$DIAR.d/90-kienzledoku-commander.conf"
  systemctl disable "$UNIT" || true
  systemctl daemon-reload
  for role in "$ASR" "$DIAR"; do
    if [[ -f "$STATE/was-active-$role" ]]; then systemctl restart "$role"; else systemctl stop "$role"; fi
  done
  if [[ -f "$STATE/was-enabled-$LLM" ]]; then systemctl enable "$LLM"; fi
  if [[ -f "$STATE/was-active-$LLM" ]]; then systemctl start "$LLM"; fi
  echo 'Originale Worker und ursprünglicher LLM-Dienstzustand wiederhergestellt.'
}
if [[ "$ACTION" == --rollback ]]; then rollback; exit; fi

# This installer targets the audited existing deployment; unknown sources fail closed.
WHISPER=${WHISPER_SOURCE:-/opt/kienzlefon-ai/python/asr-venv/lib/python3.12/site-packages/whisperlivekit/basic_server.py}
DIAR_SOURCE=${DIAR_SOURCE:-/opt/kienzlefon-ai-v2/scripts/diarization_server.py}
WORKER_USER=$(systemctl show "$ASR" --property=User --value)
[[ -n "$WORKER_USER" && "$WORKER_USER" != root ]] || { echo 'ASR muss unter einem eigenen Benutzer laufen.' >&2; exit 1; }
DIAR_USER=$(systemctl show "$DIAR" --property=User --value)
DIAR_USER=${DIAR_USER:-root}
[[ "$DIAR_USER" == "$WORKER_USER" || "$DIAR_USER" == root ]] || { echo 'Diarisierung muss als ASR-Benutzer oder root laufen.' >&2; exit 1; }
DIAR_MODE=0700
[[ "$DIAR_USER" != root ]] || DIAR_MODE=0750
[[ "$WORKER_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
WORKER_GROUP=$(id -gn "$WORKER_USER")
PYTHONPATH="$SOURCE" "$PY" -m kienzledoku_commander.patch_workers --whisper "$WHISPER" --diar "$DIAR_SOURCE" --backup "$BACKUP" --check
if [[ "$ACTION" == --check ]]; then
  echo 'Nur geprüft; keine Dateien oder laufenden Dienste verändert.'
  exit
fi
if systemctl is-active --quiet "$UNIT"; then
  echo 'Commander ist aktiv. Für ein Update zuerst kontrolliert stoppen.' >&2
  exit 1
fi
install -d -m 0755 "$PREFIX" "$CONFIG"
install -d -m 0700 "$STATE"
if [[ ! -f "$STATE/activation-snapshot" ]]; then
  for role in "$ASR" "$DIAR" "$LLM"; do
    if systemctl is-active --quiet "$role"; then touch "$STATE/was-active-$role"; fi
  done
  if systemctl is-enabled --quiet "$LLM"; then touch "$STATE/was-enabled-$LLM"; fi
  touch "$STATE/activation-snapshot"
fi
install -d -m 0700 -o "$WORKER_USER" -g "$WORKER_GROUP" /run/kienzledoku-commander
install -d -m "$DIAR_MODE" -o "$DIAR_USER" -g "$WORKER_GROUP" /run/kienzledoku-commander-diar
cp -a "$SOURCE/kienzledoku_commander" "$PREFIX/"
find "$PREFIX/kienzledoku_commander" -type d -name __pycache__ -exec rm -rf {} +
install -m 0644 "$SOURCE/kienzledoku_document.py" "$SOURCE/kienzledoku_commander_client.py" "$SOURCE/prompt_documentation.txt" "$PREFIX/"
chown -R root:root "$PREFIX"
chmod -R go-w "$PREFIX"
if [[ ! -f "$CONFIG/commander.toml" ]]; then install -m 0644 "$SOURCE/server-linux/commander/commander.toml" "$CONFIG/commander.toml"; fi
PYTHONPATH="$PREFIX" "$PY" -m kienzledoku_commander --config "$CONFIG/commander.toml" --check-config

for role in "$ASR" "$DIAR"; do
  install -d -m 0755 "/etc/systemd/system/$role.d"
  file="/etc/systemd/system/$role.d/90-kienzledoku-commander.conf"
  if [[ -f "$file" ]] && ! grep -q '^# kienzledoku-commander$' "$file"; then
    echo 'Unbekanntes Drop-in wird nicht überschrieben.' >&2; exit 1
  fi
done
PYTHONPATH="$PREFIX" "$PY" -m kienzledoku_commander.patch_workers --whisper "$WHISPER" --diar "$DIAR_SOURCE" --backup "$BACKUP"
for role in "$ASR" "$DIAR"; do
  CONTROL_DIR=/run/kienzledoku-commander
  [[ "$role" != "$DIAR" ]] || CONTROL_DIR=/run/kienzledoku-commander-diar
  cat > "/etc/systemd/system/$role.d/90-kienzledoku-commander.conf" <<EOF
# kienzledoku-commander
[Service]
Environment=PYTHONPATH=/opt/kienzledoku-commander
Environment=KIENZLEDOKU_COMMANDER_CONTROL_DIR=$CONTROL_DIR
EOF
  if [[ "$role" == "$DIAR" && "$DIAR_USER" == root ]]; then
    echo "Environment=KIENZLEDOKU_COMMANDER_CONTROL_GROUP=$WORKER_GROUP" >> "/etc/systemd/system/$role.d/90-kienzledoku-commander.conf"
  fi
done
cat > /etc/tmpfiles.d/kienzledoku-commander.conf <<EOF
d /run/kienzledoku-commander 0700 $WORKER_USER $WORKER_GROUP -
d /run/kienzledoku-commander-diar $DIAR_MODE $DIAR_USER $WORKER_GROUP -
EOF
cat > "/etc/systemd/system/$UNIT" <<EOF
[Unit]
Description=Kienzledoku Commander – Modellumschaltung und Anfragequeue
Wants=$ASR $DIAR
After=$ASR $DIAR $LLM
Conflicts=$LLM

[Service]
Type=simple
User=$WORKER_USER
Group=$WORKER_GROUP
WorkingDirectory=$PREFIX
Environment=PYTHONPATH=$PREFIX
EnvironmentFile=-$CONFIG/token.env
ExecStart=$PY -m kienzledoku_commander --config $CONFIG/commander.toml
Restart=on-failure
RestartSec=3
TimeoutStopSec=900
KillMode=control-group
RuntimeDirectory=kienzledoku-commander
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
if [[ "$ACTION" == --activate ]]; then
  for role in "$ASR" "$DIAR" "$LLM"; do
    rm -f "$STATE/was-active-$role"
    if systemctl is-active --quiet "$role"; then touch "$STATE/was-active-$role"; fi
  done
  rm -f "$STATE/was-enabled-$LLM"
  if systemctl is-enabled --quiet "$LLM"; then touch "$STATE/was-enabled-$LLM"; fi
  trap 'echo "Aktivierung fehlgeschlagen; automatischer Rückbau." >&2; rollback' ERR
  systemctl disable --now "$LLM"
  systemctl restart "$ASR" "$DIAR"
  systemctl enable --now "$UNIT"
  PYTHONPATH="$PREFIX" "$PY" - <<'PY'
import json, time, urllib.request
from kienzledoku_commander.config import load_settings
cfg = load_settings('/etc/kienzledoku-commander/commander.toml')
host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(cfg.host, cfg.host)
if ':' in host: host = '[' + host + ']'
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(180):
    try:
        with http.open('http://%s:%d/health' % (host, cfg.port), timeout=1) as r:
            value = json.load(r)
            if value['status'] == 'ok' and value['asr_ready']: break
    except OSError: pass
    time.sleep(1)
else: raise SystemExit('Commander wird nicht bereit.')
PY
  trap - ERR
  echo 'Commander aktiviert. Client-Endpunkte und optional LAN-Bind/Token einstellen.'
else
  echo 'Installiert, noch nicht aktiviert. Kein laufender Dienst wurde neu gestartet.'
fi
