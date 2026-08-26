#!/bin/bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
    SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
else
    SCRIPT_DIR=""
fi
ARCHIVE_URL="${KIENZLEDOKU_ARCHIVE_URL:-https://github.com/thomaskien/kienzledoku/archive/refs/heads/main.tar.gz}"

# Bei `curl .../install_linux.sh | bash` liegt nur dieses Skript vor. In diesem
# Fall wird der dazugehoerige, offen einsehbare Quellbaum in ein temporaeres
# Verzeichnis geladen und von dort derselbe Installer ausgefuehrt.
if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/native/KienzledokuWindowLinux.c" ]; then
    for bootstrap_command in curl tar mktemp; do
        if ! command -v "$bootstrap_command" >/dev/null 2>&1; then
            echo "FEHLER: Fuer die GitHub-Installation fehlt: $bootstrap_command" >&2
            exit 1
        fi
    done
    BOOTSTRAP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kienzledoku-github.XXXXXX")"
    cleanup_bootstrap() {
        rm -rf -- "$BOOTSTRAP_DIR"
    }
    trap cleanup_bootstrap EXIT HUP INT TERM
    echo "Kienzledoku-Quellcode wird von GitHub geladen ..."
    curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$BOOTSTRAP_DIR"
    CHECKOUT_DIRS=("$BOOTSTRAP_DIR"/kienzledoku-*)
    if [ "${#CHECKOUT_DIRS[@]}" -ne 1 ] || [ ! -x "${CHECKOUT_DIRS[0]}/install_linux.sh" ]; then
        echo "FEHLER: Das GitHub-Archiv enthaelt keinen gueltigen Kienzledoku-Installer." >&2
        exit 1
    fi
    # Die Skript-Pipe ist kein Eingabekanal fuer die Installationsfragen.
    # In einer interaktiven Shell werden sie deshalb vom steuernden Terminal
    # gelesen; automatisierte Aufrufe koennen weiterhin ohne TTY arbeiten.
    if ( : </dev/tty ) 2>/dev/null; then
        if "${CHECKOUT_DIRS[0]}/install_linux.sh" "$@" </dev/tty; then
            INSTALL_STATUS=0
        else
            INSTALL_STATUS=$?
        fi
    elif "${CHECKOUT_DIRS[0]}/install_linux.sh" "$@"; then
        INSTALL_STATUS=0
    else
        INSTALL_STATUS=$?
    fi
    trap - EXIT HUP INT TERM
    cleanup_bootstrap
    exit "$INSTALL_STATUS"
fi

SELF_TEST=0
SKIP_PACKAGES=0
REGISTER_LEGACY=0

usage() {
    cat <<'EOF'
Aufruf: ./install_linux.sh [Optionen]

Installiert den schlanken Kienzledoku-Client für Ubuntu 24.04 LTS.
Die KI-Serverkomponenten werden nicht installiert.

Optionen:
  --skip-packages       apt-Pakete nicht installieren oder aktualisieren
  --legacy-url-schemes  zusätzlich T2demo:// und whisperdoku:// registrieren
  --self-test           nur den netzwerkfreien statischen Selbsttest ausführen
  --help                diese Hilfe anzeigen
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --skip-packages) SKIP_PACKAGES=1 ;;
        --legacy-url-schemes) REGISTER_LEGACY=1 ;;
        --self-test) SELF_TEST=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "FEHLER: Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

static_self_test() {
    required_files="
kienzledoku.py
kienzledoku_document.py
kienzledoku_speech.py
kienzledoku_asr_v6.py
start_kienzledoku_asr.sh
requirements-asr-client.txt
prompt_documentation.txt
native/KienzledokuWindowLinux.c
linux/kienzledoku-launcher.sh
linux/kienzledoku.desktop
linux/kienzledoku.apparmor
build_native_window_linux.sh
"
    for relative_path in $required_files; do
        if [ ! -f "$SCRIPT_DIR/$relative_path" ]; then
            echo "SELF-TEST FEHLER: Datei fehlt: $relative_path" >&2
            return 1
        fi
    done
    bash -n "$SCRIPT_DIR/install_linux.sh"
    bash -n "$SCRIPT_DIR/build_native_window_linux.sh"
    bash -n "$SCRIPT_DIR/linux/kienzledoku-launcher.sh"
    bash -n "$SCRIPT_DIR/start_kienzledoku_asr.sh"
    python3 - "$SCRIPT_DIR" <<'PY'
import os
import sys

root = sys.argv[1]
for name in (
    "kienzledoku.py",
    "kienzledoku_document.py",
    "kienzledoku_speech.py",
    "kienzledoku_asr_v6.py",
):
    path = os.path.join(root, name)
    with open(path, "r", encoding="utf-8") as handle:
        compile(handle.read(), path, "exec")

profile_path = os.path.join(root, "linux", "kienzledoku.apparmor")
with open(profile_path, "r", encoding="utf-8") as handle:
    profile = handle.read()
for required in (
    "/usr/local/libexec/kienzledoku/kienzledoku_window_linux",
    "flags=(unconfined)",
    "userns,",
):
    if required not in profile:
        raise SystemExit("AppArmor-Profil unvollständig: " + required)
if "apparmor_restrict_unprivileged_userns=0" in profile:
    raise SystemExit("AppArmor-Profil darf den Ubuntu-Systemschutz nicht abschalten")
PY
    if command -v pkg-config >/dev/null 2>&1 && \
       pkg-config --exists gtk4 webkitgtk-6.0; then
        build_dir="$(mktemp -d "${TMPDIR:-/tmp}/kienzledoku-linux-window.XXXXXX")"
        trap 'rm -rf -- "$build_dir"' EXIT HUP INT TERM
        "$SCRIPT_DIR/build_native_window_linux.sh" "$build_dir/kienzledoku_window_linux"
    fi
    echo "SELF-TEST OK - Kienzledoku Linux-Installer"
}

if [ "$SELF_TEST" -eq 1 ]; then
    static_self_test
    exit $?
fi

if [ ! -r /etc/os-release ]; then
    echo "FEHLER: /etc/os-release fehlt; unterstützt wird Ubuntu 24.04 LTS." >&2
    exit 1
fi
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "FEHLER: Unterstützt wird ausschließlich Ubuntu 24.04 LTS." >&2
    echo "Gefunden: ${PRETTY_NAME:-unbekannt}" >&2
    exit 1
fi
if [ "$(uname -m)" != "x86_64" ]; then
    echo "FEHLER: Der T2med-Linux-Client wird zunächst nur für x86_64 unterstützt." >&2
    exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
    echo "FEHLER: sudo wird für die geschützte Fenster- und AppArmor-Installation benötigt." >&2
    exit 1
fi

if [ "$SKIP_PACKAGES" -eq 0 ]; then
    echo "Ubuntu-Abhängigkeiten werden installiert ..."
    sudo apt-get update
    if ! apt-cache show libwebkitgtk-6.0-dev >/dev/null 2>&1; then
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y universe
        sudo apt-get update
    fi
    sudo apt-get install -y \
        apparmor \
        build-essential \
        ca-certificates \
        desktop-file-utils \
        gnome-keyring \
        libgtk-4-dev \
        libnotify-bin \
        libportaudio2 \
        libsecret-tools \
        libwebkitgtk-6.0-dev \
        pkg-config \
        python3 \
        python3-pip \
        python3-venv \
        xdg-utils
fi

for command_name in apparmor_parser python3 cc desktop-file-validate install pkg-config xdg-mime; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "FEHLER: Erforderliches Programm fehlt: $command_name" >&2
        exit 1
    fi
done
if ! pkg-config --exists gtk4 webkitgtk-6.0; then
    echo "FEHLER: GTK 4/WebKitGTK 6.0 Entwicklungsdateien fehlen." >&2
    echo "Bitte Ubuntu Universe aktivieren und libgtk-4-dev sowie libwebkitgtk-6.0-dev installieren." >&2
    exit 1
fi

PYTHON3="$(command -v python3)"
"$PYTHON3" - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("FEHLER: Python 3.9 oder neuer erforderlich; gefunden: " + sys.version.split()[0])
print("Python:", sys.executable, sys.version.split()[0])
PY

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
DATA_DIR="$DATA_HOME/kienzledoku"
CONFIG_DIR="$CONFIG_HOME/kienzledoku"
STATE_DIR="$STATE_HOME/kienzledoku"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="$DATA_HOME/applications"
CONFIG_PATH="$CONFIG_DIR/config.json"
LOG_PATH="$STATE_DIR/kienzledoku.log"
LAUNCHER_PATH="$BIN_DIR/kienzledoku"
DESKTOP_PATH="$APPLICATIONS_DIR/kienzledoku.desktop"
SYSTEM_HELPER_DIR="/usr/local/libexec/kienzledoku"
SYSTEM_HELPER_PATH="$SYSTEM_HELPER_DIR/kienzledoku_window_linux"
APPARMOR_PROFILE_PATH="/etc/apparmor.d/kienzledoku-window"

for xdg_path in "$DATA_HOME" "$CONFIG_HOME" "$STATE_HOME"; do
    case "$xdg_path" in
        /*) ;;
        *) echo "FEHLER: XDG-Verzeichnisse müssen absolute Pfade sein: $xdg_path" >&2; exit 1 ;;
    esac
done

mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$STATE_DIR" "$BIN_DIR" "$APPLICATIONS_DIR"
chmod 700 "$DATA_DIR" "$CONFIG_DIR" "$STATE_DIR"
touch "$LOG_PATH"
chmod 600 "$LOG_PATH"

stored_service_part() {
    "$PYTHON3" - "$CONFIG_PATH" "$1" "$2" "$3" <<'PY'
import json
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

stored_t2med_host() {
    "$PYTHON3" - "$CONFIG_PATH" "$1" <<'PY'
import json
import sys

path, fallback = sys.argv[1:]
value = fallback
try:
    with open(path, "r", encoding="utf-8") as handle:
        configured = json.load(handle).get("t2med", {}).get("fhir_host", "")
    if isinstance(configured, str) and configured.strip():
        value = configured.strip()
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

prompt_t2med_host() {
    default_host="$1"
    override_host="$2"
    while true; do
        if [ -n "$override_host" ]; then
            chosen_host="$override_host"
        elif [ "${KIENZLEDOKU_INSTALL_NONINTERACTIVE:-0}" = "1" ]; then
            chosen_host="$default_host"
        else
            printf 'T2med-FHIR-Server (Host/IP) [%s]: ' "$default_host"
            IFS= read -r chosen_host
            chosen_host="${chosen_host:-$default_host}"
        fi
        if validation_error="$(validate_host_and_port "$chosen_host" 443 2>&1)"; then
            T2MED_HOST="$chosen_host"
            return 0
        fi
        echo "FEHLER: $validation_error" >&2
        if [ "${KIENZLEDOKU_INSTALL_NONINTERACTIVE:-0}" = "1" ] || [ -n "$override_host" ]; then
            return 1
        fi
    done
}

echo
echo "T2med-FHIR-Ziel für diesen Ubuntu-Arbeitsplatz"
T2MED_DEFAULT_HOST="$(stored_t2med_host 10.0.83.120)"
prompt_t2med_host "$T2MED_DEFAULT_HOST" "${KIENZLEDOKU_INSTALL_T2MED_HOST:-}"

echo
echo "Kienzlefon-Dienste für diesen Ubuntu-Arbeitsplatz"
echo "Die Serverkomponenten bleiben getrennt und dürfen auf einem anderen Rechner laufen."
echo

ASR_DEFAULT_HOST="$(stored_service_part asr host 127.0.0.1)"
ASR_DEFAULT_PORT="$(stored_service_part asr port 8179)"
prompt_service "ASR" "$ASR_DEFAULT_HOST" "$ASR_DEFAULT_PORT" \
    "${KIENZLEDOKU_INSTALL_ASR_HOST:-}" "${KIENZLEDOKU_INSTALL_ASR_PORT:-}"
ASR_HOST="$SERVICE_HOST"
ASR_URL="$(compose_service_url "$SERVICE_HOST" "$SERVICE_PORT")"

DIARIZATION_DEFAULT_HOST="$(stored_service_part diarization host "$ASR_HOST")"
DIARIZATION_DEFAULT_PORT="$(stored_service_part diarization port 8183)"
prompt_service "Diarisierung" "$DIARIZATION_DEFAULT_HOST" "$DIARIZATION_DEFAULT_PORT" \
    "${KIENZLEDOKU_INSTALL_DIARIZATION_HOST:-}" "${KIENZLEDOKU_INSTALL_DIARIZATION_PORT:-}"
DIARIZATION_HOST="$SERVICE_HOST"
DIARIZATION_URL="$(compose_service_url "$SERVICE_HOST" "$SERVICE_PORT")"

LLM_DEFAULT_HOST="$(stored_service_part llm host "$DIARIZATION_HOST")"
LLM_DEFAULT_PORT="$(stored_service_part llm port 8080)"
prompt_service "LLM" "$LLM_DEFAULT_HOST" "$LLM_DEFAULT_PORT" \
    "${KIENZLEDOKU_INSTALL_LLM_HOST:-}" "${KIENZLEDOKU_INSTALL_LLM_PORT:-}"
LLM_URL="$(compose_service_url "$SERVICE_HOST" "$SERVICE_PORT")"

"$PYTHON3" - "$CONFIG_PATH" "$T2MED_HOST" "$ASR_URL" "$DIARIZATION_URL" "$LLM_URL" <<'PY'
import json
import os
import sys
import tempfile

path, t2med_host, asr_url, diarization_url, llm_url = sys.argv[1:]
payload = {
    "version": 1,
    "t2med": {"fhir_host": t2med_host},
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

for source_name in \
    kienzledoku.py \
    kienzledoku_document.py \
    kienzledoku_speech.py \
    kienzledoku_asr_v6.py \
    start_kienzledoku_asr.sh \
    requirements-asr-client.txt \
    prompt_documentation.txt
do
    cp "$SCRIPT_DIR/$source_name" "$DATA_DIR/$source_name"
done
chmod 700 "$DATA_DIR"/*.py "$DATA_DIR/start_kienzledoku_asr.sh"
chmod 600 "$DATA_DIR/requirements-asr-client.txt" "$DATA_DIR/prompt_documentation.txt"

WINDOW_BUILD_PATH="$DATA_DIR/.kienzledoku_window_linux.build"
"$SCRIPT_DIR/build_native_window_linux.sh" "$WINDOW_BUILD_PATH"
sudo install -d -o root -g root -m 0755 "$SYSTEM_HELPER_DIR"
sudo install -o root -g root -m 0755 "$WINDOW_BUILD_PATH" "$SYSTEM_HELPER_PATH"
rm -f -- "$WINDOW_BUILD_PATH" "$DATA_DIR/kienzledoku_window_linux"

# Remove the previously loaded definition before replacing its source file.
# This also migrates the temporary per-user profile used during the first
# Ubuntu field diagnosis without leaving that broader attachment active.
if [ -f "$APPARMOR_PROFILE_PATH" ]; then
    sudo apparmor_parser -R "$APPARMOR_PROFILE_PATH" >/dev/null 2>&1 || true
fi
sudo install -o root -g root -m 0644 \
    "$SCRIPT_DIR/linux/kienzledoku.apparmor" "$APPARMOR_PROFILE_PATH"
sudo apparmor_parser -r "$APPARMOR_PROFILE_PATH"

PY_MM="$("$PYTHON3" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_TAG="$(printf '%s' "$PY_MM" | tr -d '.')"
ARCH="$(uname -m)"
VENV_DIR="$DATA_DIR/venvs/client-v6-${ARCH}-py${PY_TAG}"
if [ -d "$VENV_DIR" ] && \
   { [ ! -x "$VENV_DIR/bin/python3" ] || ! "$VENV_DIR/bin/python3" -c 'import sys' >/dev/null 2>&1; }; then
    rm -rf -- "$VENV_DIR"
fi
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON3" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python3" -m pip install --disable-pip-version-check \
    -r "$DATA_DIR/requirements-asr-client.txt"
"$VENV_DIR/bin/python3" -c 'import sounddevice; print("Audio-Client: sounddevice", sounddevice.__version__)'

"$PYTHON3" - \
    "$SCRIPT_DIR/linux/kienzledoku-launcher.sh" \
    "$LAUNCHER_PATH" \
    "$PYTHON3" \
    "$DATA_DIR" \
    "$LOG_PATH" <<'PY'
import os
import shlex
import sys

template_path, path, python, data_dir, log_path = sys.argv[1:]
with open(template_path, "r", encoding="utf-8") as handle:
    content = handle.read()
content = (content.replace("@PYTHON3@", shlex.quote(python))
                  .replace("@DATA_DIR@", shlex.quote(data_dir))
                  .replace("@LOG_PATH@", shlex.quote(log_path)))
with open(path, "w", encoding="utf-8") as handle:
    handle.write(content)
os.chmod(path, 0o700)
PY

"$PYTHON3" - \
    "$SCRIPT_DIR/linux/kienzledoku.desktop" \
    "$DESKTOP_PATH" \
    "$LAUNCHER_PATH" \
    "$REGISTER_LEGACY" <<'PY'
import os
import sys

template_path, path, launcher, register_legacy = sys.argv[1:]
escaped = (launcher.replace("\\", "\\\\")
                   .replace('"', '\\"')
                   .replace("`", "\\`")
                   .replace("$", "\\$"))
mime_types = "x-scheme-handler/kienzledoku;"
if register_legacy == "1":
    mime_types += "x-scheme-handler/t2demo;x-scheme-handler/whisperdoku;"
with open(template_path, "r", encoding="utf-8") as handle:
    content = handle.read()
content = (content.replace("@LAUNCHER_EXEC@", escaped)
                  .replace("@MIME_TYPES@", mime_types))
with open(path, "w", encoding="utf-8") as handle:
    handle.write(content)
os.chmod(path, 0o600)
PY

desktop-file-validate "$DESKTOP_PATH"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR"
fi
xdg-mime default kienzledoku.desktop x-scheme-handler/kienzledoku
if [ "$(xdg-mime query default x-scheme-handler/kienzledoku)" != "kienzledoku.desktop" ]; then
    echo "FEHLER: kienzledoku:// konnte nicht als URL-Handler registriert werden." >&2
    exit 1
fi
if [ "$REGISTER_LEGACY" -eq 1 ]; then
    xdg-mime default kienzledoku.desktop x-scheme-handler/t2demo
    xdg-mime default kienzledoku.desktop x-scheme-handler/whisperdoku
fi

"$PYTHON3" "$DATA_DIR/kienzledoku.py" --self-test

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
echo "Kienzledoku 1.3.1 für Ubuntu 24.04 wurde installiert."
echo "Programmdateien: $DATA_DIR"
echo "Fensterprogramm: $SYSTEM_HELPER_PATH"
echo "AppArmor-Profil: $APPARMOR_PROFILE_PATH"
echo "Konfiguration:   $CONFIG_PATH"
echo "Diagnoseprotokoll: $LOG_PATH"
echo "URL-Schema: kienzledoku://"
if [ "$REGISTER_LEGACY" -eq 1 ]; then
    echo "Kompatibilitätsschemata: T2demo:// und whisperdoku://"
fi
echo "Eigener API-Key: ./set_api_key_linux.sh"
echo
echo "Nächster Test: TESTPATIENTEN in T2med öffnen und den Kienzledoku-Button betätigen."
