#!/bin/bash
set -e

APP_NAME="Kienzledoku.app"
LOG_DIR="$HOME/Library/Logs"
LOG_PATH="$LOG_DIR/Kienzledoku.log"
APP_DIR="$HOME/Applications/$APP_NAME"
LEGACY_APP_DIR="$HOME/Applications/WhisperDoku T2med Test.app"
SUPPORT_DIR="$HOME/Library/Application Support/Kienzledoku"
CONFIG_PATH="$SUPPORT_DIR/config.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_PY="$SCRIPT_DIR/kienzledoku.py"
SOURCE_DOCUMENT="$SCRIPT_DIR/kienzledoku_document.py"
SOURCE_SPEECH="$SCRIPT_DIR/kienzledoku_speech.py"
SOURCE_ASR="$SCRIPT_DIR/kienzledoku_asr_v6.py"
SOURCE_ASR_RUNNER="$SCRIPT_DIR/start_kienzledoku_asr.sh"
SOURCE_ASR_REQUIREMENTS="$SCRIPT_DIR/requirements-asr-client.txt"
SOURCE_WINDOW="$SCRIPT_DIR/kienzledoku_window"
SOURCE_PROMPT="$SCRIPT_DIR/prompt_documentation.txt"

find_python3() {
  python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
  }

  if [ -n "${KIENZLEDOKU_PYTHON:-}" ]; then
    if [ -x "$KIENZLEDOKU_PYTHON" ]; then
      if python_is_supported "$KIENZLEDOKU_PYTHON"; then
        printf '%s\n' "$KIENZLEDOKU_PYTHON"
        return 0
      fi
      echo "FEHLER: KIENZLEDOKU_PYTHON benötigt Python >= 3.9: $KIENZLEDOKU_PYTHON" >&2
      return 1
    fi
    if command -v "$KIENZLEDOKU_PYTHON" >/dev/null 2>&1; then
      candidate="$(command -v "$KIENZLEDOKU_PYTHON")"
      if python_is_supported "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
      echo "FEHLER: KIENZLEDOKU_PYTHON benötigt Python >= 3.9: $candidate" >&2
      return 1
    fi
    echo "FEHLER: KIENZLEDOKU_PYTHON ist nicht ausführbar: $KIENZLEDOKU_PYTHON" >&2
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

  echo "FEHLER: Python 3 nicht gefunden. Benötigt wird Python >= 3.9." >&2
  return 1
}

PYTHON3="$(find_python3)" || exit 1

"$PYTHON3" - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("FEHLER: Python 3.9 oder neuer erforderlich; gefunden: " + sys.version.split()[0])
print("Python:", sys.executable, sys.version.split()[0])
PY

mkdir -p "$HOME/Applications" "$SUPPORT_DIR" "$LOG_DIR"

stored_service_part() {
  "$PYTHON3" - "$CONFIG_PATH" "$1" "$2" "$3" <<'PY'
import json
import os
import sys
import urllib.parse

path, service, part, fallback = sys.argv[1:]
value = fallback
try:
    with open(path, "r", encoding="utf-8") as handle:
        url = json.load(handle).get("services", {}).get(service, "")
    parsed = urllib.parse.urlparse(url)
    if part == "host" and parsed.hostname:
        value = parsed.hostname
    elif part == "port" and parsed.port:
        value = str(parsed.port)
except (OSError, ValueError, TypeError, AttributeError):
    pass
print(value)
PY
}

validate_host_and_port() {
  "$PYTHON3" - "$1" "$2" <<'PY'
import ipaddress
import re
import sys

host, port_text = sys.argv[1:]
if not host or any(char.isspace() for char in host):
    raise SystemExit("Host/IP darf nicht leer sein und keine Leerzeichen enthalten.")
if "://" in host or "/" in host or "@" in host:
    raise SystemExit("Bitte nur Hostname oder IP eingeben, ohne http:// und ohne Pfad.")
try:
    ipaddress.ip_address(host)
except ValueError:
    if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
        raise SystemExit("Ungültiger Hostname oder ungültige IP-Adresse: " + host)
try:
    port = int(port_text)
except ValueError:
    raise SystemExit("Der Port muss eine Zahl sein.")
if not 1 <= port <= 65535:
    raise SystemExit("Der Port muss zwischen 1 und 65535 liegen.")
PY
}

compose_service_url() {
  "$PYTHON3" - "$1" "$2" <<'PY'
import ipaddress
import sys

host, port = sys.argv[1:]
try:
    is_ipv6 = ipaddress.ip_address(host).version == 6
except ValueError:
    is_ipv6 = False
print("http://[%s]:%s" % (host, port) if is_ipv6 else "http://%s:%s" % (host, port))
PY
}

prompt_service() {
  service_label="$1"
  default_host="$2"
  default_port="$3"
  override_host="$4"
  override_port="$5"

  while true; do
    if [ -n "$override_host" ]; then
      chosen_host="$override_host"
    elif [ "${KIENZLEDOKU_INSTALL_NONINTERACTIVE:-0}" = "1" ]; then
      chosen_host="$default_host"
    else
      printf '%s-Server (Host/IP) [%s]: ' "$service_label" "$default_host"
      IFS= read -r chosen_host
      chosen_host="${chosen_host:-$default_host}"
    fi

    if [ -n "$override_port" ]; then
      chosen_port="$override_port"
    elif [ "${KIENZLEDOKU_INSTALL_NONINTERACTIVE:-0}" = "1" ]; then
      chosen_port="$default_port"
    else
      printf '%s-Port [%s]: ' "$service_label" "$default_port"
      IFS= read -r chosen_port
      chosen_port="${chosen_port:-$default_port}"
    fi

    if validation_error="$(validate_host_and_port "$chosen_host" "$chosen_port" 2>&1)"; then
      SERVICE_HOST="$chosen_host"
      SERVICE_PORT="$chosen_port"
      return 0
    fi
    echo "FEHLER: $validation_error" >&2
    if [ "${KIENZLEDOKU_INSTALL_NONINTERACTIVE:-0}" = "1" ] || [ -n "$override_host$override_port" ]; then
      return 1
    fi
  done
}

echo
echo "Kienzlefon-Dienste für diesen Mac"
echo "Nur Hostname/IP und Port eingeben; ASR, Diarisierung und LLM dürfen auf unterschiedlichen Rechnern laufen."
echo

ASR_DEFAULT_HOST="$(stored_service_part asr host 127.0.0.1)"
ASR_DEFAULT_PORT="$(stored_service_part asr port 8179)"
prompt_service "ASR" "$ASR_DEFAULT_HOST" "$ASR_DEFAULT_PORT" \
  "${KIENZLEDOKU_INSTALL_ASR_HOST:-}" "${KIENZLEDOKU_INSTALL_ASR_PORT:-}"
ASR_HOST="$SERVICE_HOST"
ASR_PORT="$SERVICE_PORT"
ASR_URL="$(compose_service_url "$ASR_HOST" "$ASR_PORT")"

DIARIZATION_DEFAULT_HOST="$(stored_service_part diarization host "$ASR_HOST")"
DIARIZATION_DEFAULT_PORT="$(stored_service_part diarization port 8183)"
prompt_service "Diarisierung" "$DIARIZATION_DEFAULT_HOST" "$DIARIZATION_DEFAULT_PORT" \
  "${KIENZLEDOKU_INSTALL_DIARIZATION_HOST:-}" "${KIENZLEDOKU_INSTALL_DIARIZATION_PORT:-}"
DIARIZATION_HOST="$SERVICE_HOST"
DIARIZATION_PORT="$SERVICE_PORT"
DIARIZATION_URL="$(compose_service_url "$DIARIZATION_HOST" "$DIARIZATION_PORT")"

LLM_DEFAULT_HOST="$(stored_service_part llm host "$DIARIZATION_HOST")"
LLM_DEFAULT_PORT="$(stored_service_part llm port 8080)"
prompt_service "LLM" "$LLM_DEFAULT_HOST" "$LLM_DEFAULT_PORT" \
  "${KIENZLEDOKU_INSTALL_LLM_HOST:-}" "${KIENZLEDOKU_INSTALL_LLM_PORT:-}"
LLM_HOST="$SERVICE_HOST"
LLM_PORT="$SERVICE_PORT"
LLM_URL="$(compose_service_url "$LLM_HOST" "$LLM_PORT")"

"$PYTHON3" - "$CONFIG_PATH" \
  "$ASR_URL" \
  "$DIARIZATION_URL" \
  "$LLM_URL" <<'PY'
import json
import os
import sys
import tempfile

path, asr_url, diarization_url, llm_url = sys.argv[1:]
payload = {
    "version": 1,
    "services": {
        "asr": asr_url,
        "diarization": diarization_url,
        "llm": llm_url,
    },
}
directory = os.path.dirname(path)
descriptor, temporary_path = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=directory)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)
finally:
    if os.path.exists(temporary_path):
        os.unlink(temporary_path)
PY

touch "$LOG_PATH"
chmod 600 "$LOG_PATH"
cp "$SOURCE_PY" "$SUPPORT_DIR/kienzledoku.py"
cp "$SOURCE_DOCUMENT" "$SUPPORT_DIR/kienzledoku_document.py"
cp "$SOURCE_SPEECH" "$SUPPORT_DIR/kienzledoku_speech.py"
cp "$SOURCE_ASR" "$SUPPORT_DIR/kienzledoku_asr_v6.py"
cp "$SOURCE_ASR_RUNNER" "$SUPPORT_DIR/start_kienzledoku_asr.sh"
cp "$SOURCE_ASR_REQUIREMENTS" "$SUPPORT_DIR/requirements-asr-client.txt"
cp "$SOURCE_WINDOW" "$SUPPORT_DIR/kienzledoku_window"
cp "$SOURCE_PROMPT" "$SUPPORT_DIR/prompt_documentation.txt"
chmod 700 \
  "$SUPPORT_DIR/kienzledoku.py" \
  "$SUPPORT_DIR/kienzledoku_document.py" \
  "$SUPPORT_DIR/kienzledoku_speech.py" \
  "$SUPPORT_DIR/kienzledoku_asr_v6.py" \
  "$SUPPORT_DIR/start_kienzledoku_asr.sh" \
  "$SUPPORT_DIR/kienzledoku_window"
chmod 600 "$SUPPORT_DIR/prompt_documentation.txt" "$SUPPORT_DIR/requirements-asr-client.txt"
/usr/bin/codesign --force --sign - "$SUPPORT_DIR/kienzledoku_window"
/usr/bin/codesign --verify --strict --all-architectures "$SUPPORT_DIR/kienzledoku_window"

# Escape AppleScript string literals.
escape_as_string() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}
PY_AS="$(escape_as_string "$PYTHON3")"
SCRIPT_AS="$(escape_as_string "$SUPPORT_DIR/kienzledoku.py")"
LOG_AS="$(escape_as_string "$LOG_PATH")"
TMP_AS="$(mktemp -t kienzledoku)"
cat > "$TMP_AS" <<EOF
property pythonPath : "$PY_AS"
property scriptPath : "$SCRIPT_AS"
property logPath : "$LOG_AS"

on run
    display dialog "Kienzledoku 1.2 ist installiert. Die Anwendung wird aus T2med über T2demo:// bzw. kienzledoku:// gestartet." buttons {"OK"} default button "OK"
end run

on open location theURL
    -- Log only that macOS invoked the URL handler. Never write the URL itself (OAuth token).
    set stamp to do shell script "/bin/date '+%Y-%m-%dT%H:%M:%S%z'"
    set logLine to stamp & " | macOS URL handler invoked"
    do shell script "/bin/echo " & (quoted form of logLine) & " >> " & (quoted form of logPath)
    set cmd to (quoted form of pythonPath) & " " & (quoted form of scriptPath) & " --deep-link " & (quoted form of theURL) & " >> " & (quoted form of logPath) & " 2>&1 &"
    do shell script cmd
end open location
EOF

rm -rf "$APP_DIR"
/usr/bin/osacompile -o "$APP_DIR" "$TMP_AS"
rm -f "$TMP_AS"

PLIST="$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIdentifier" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string de.kienzledoku.app" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :CFBundleShortVersionString" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 1.2" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :CFBundleVersion" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1.2" "$PLIST"
# T2demo and whisperdoku remain registered for compatibility; kienzledoku is canonical.
/usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string de.kienzledoku.t2med" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string T2demo" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:1 string whisperdoku" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:2 string kienzledoku" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :LSUIElement" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST"
/usr/libexec/PlistBuddy -c "Delete :NSMicrophoneUsageDescription" "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string Kienzledoku benötigt das Mikrofon für die medizinische Gesprächsdokumentation." "$PLIST"

# osacompile signs before the URL/privacy keys above are added. Re-sign the
# finished local bundle so macOS TCC can bind microphone consent to its stable ID.
/usr/bin/codesign --force --deep --sign - "$APP_DIR"
/usr/bin/codesign --verify --deep --strict "$APP_DIR"

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "$LSREGISTER" ]; then
  # The v0.1.2 app claims the same T2demo:// scheme. Unregister it without
  # deleting the legacy app, then register Kienzledoku last.
  if [ -d "$LEGACY_APP_DIR" ]; then
    "$LSREGISTER" -u "$LEGACY_APP_DIR" >/dev/null 2>&1 || true
  fi
  "$LSREGISTER" -f "$APP_DIR" >/dev/null 2>&1 || true
fi

"$PYTHON3" "$SUPPORT_DIR/kienzledoku.py" --self-test

check_service() {
  service_label="$1"
  service_url="$2"
  health_path="$3"
  if "$PYTHON3" - "$service_url$health_path" <<'PY'
import sys
import urllib.request

try:
    request = urllib.request.Request(sys.argv[1], headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=3) as response:
        if not 200 <= int(response.getcode()) < 300:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
  then
    echo "$service_label: OK ($service_url)"
  else
    echo "$service_label: NICHT ERREICHBAR ($service_url) – Installation wird fortgesetzt."
  fi
}

echo
echo "Verbindungsprüfung"
check_service "ASR" "$ASR_URL" "/health"
check_service "Diarisierung" "$DIARIZATION_URL" "/health"
check_service "LLM" "$LLM_URL" "/v1/models"

echo
echo "Installiert: $APP_DIR"
if [ -d "$LEGACY_APP_DIR" ]; then
  echo "Alter URL-Handler abgemeldet (nicht gelöscht): $LEGACY_APP_DIR"
fi
echo "URL-Schemes: T2demo://, whisperdoku:// und kienzledoku://"
echo "Dienstkonfiguration: $CONFIG_PATH"
echo "Diagnose-Log: $LOG_PATH"
echo "API-Key: zunächst öffentlicher T2med-Demo-Key."
echo "WICHTIG: Der Demo-Key ist auf 100 einzelne FHIR-Requests pro APS-Serverprozess begrenzt."
echo "Nach Ausschöpfen muss der T2med-/APS-Serverprozess neu gestartet werden."
echo "Für den regelmäßigen Betrieb einen eigenen Key mit set_api_key_macos.command im Schlüsselbund speichern."
echo
echo "Nächster Test: TESTPATIENTEN öffnen und den in T2med separat zugewiesenen Drittanbieter-Button betätigen."
echo "Das eigene Kienzledoku-Fenster sollte sich öffnen und die Aufnahme sofort starten."
