#!/bin/bash
# Kienzledoku Local AI for Apple Silicon / M4
# Version 1.0.0

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

VERSION="1.0.0"
ACTION="install"
MODE="ask"
COMPONENTS_OPTION="ask"
ADD_COMPONENTS_OPTION=""
INSTALL_COMPONENTS=""
LISTEN_ADDRESS_OPTION="ask"
SELECTED_COMPONENTS="llm,asr,diarization"
LISTEN_ADDRESS="127.0.0.1"
SERVICE=""
NO_START=0
ASSUME_YES=0

ORIGINAL_ARGS=("$@")
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "$0")"

INSTALL_ROOT="$HOME/Library/Application Support/Kienzledoku Local AI"
BIN_DIR="$INSTALL_ROOT/bin"
SCRIPT_INSTALL_DIR="$INSTALL_ROOT/scripts"
MODEL_DIR="$INSTALL_ROOT/models"
PYTHON_DIR="$INSTALL_ROOT/python"
SOURCE_DIR="$INSTALL_ROOT/src"
PLIST_STORE="$INSTALL_ROOT/LaunchAgents"
MODE_FILE="$INSTALL_ROOT/start-mode"
VERSIONS_FILE="$INSTALL_ROOT/versions.conf"
COMPONENTS_FILE="$INSTALL_ROOT/installed-components"
LISTEN_ADDRESS_FILE="$INSTALL_ROOT/listen-address"
MANAGER_INSTALL_PATH="$SCRIPT_INSTALL_DIR/manager_macos.sh"
LOG_DIR="$HOME/Library/Logs/Kienzledoku Local AI"
USER_PLIST_DIR="$HOME/Library/LaunchAgents"

LLM_LABEL="de.kienzledoku.local-ai.llm"
ASR_LABEL="de.kienzledoku.local-ai.asr"
DIARIZATION_LABEL="de.kienzledoku.local-ai.diarization"
ENVIRONMENT_LABEL="de.kienzledoku.local-ai.environment"

LLM_PORT=8080
ASR_PORT=8179
DIARIZATION_PORT=8183

LLAMA_REPOSITORY="https://github.com/ggml-org/llama.cpp.git"
LLAMA_REF="aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3"
LLAMA_BUILD="b9637"

QWEN_REPOSITORY="bartowski/Qwen_Qwen3.5-9B-GGUF"
QWEN_REVISION="2dcd842c59ea5eb119267064550a7a4c592b16c3"
QWEN_FILENAME="Qwen_Qwen3.5-9B-Q6_K.gguf"
QWEN_SIZE="7958818848"
QWEN_SHA256="073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef"

MLX_VERSION="0.32.0"
MLX_WHISPER_VERSION="0.4.3"
WHISPER_REPOSITORY="mlx-community/whisper-large-v3-mlx"
WHISPER_REVISION="49e6aa286ad60c14352c404340ded53710378a11"
WHISPER_WEIGHTS="weights.npz"
WHISPER_WEIGHTS_SHA256="05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d"
WHISPER_CONFIG="config.json"
WHISPER_CONFIG_SHA256="34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3"

PYANNOTE_AUDIO_VERSION="4.0.7"
PYANNOTE_REPOSITORY="pyannote/speaker-diarization-community-1"
PYANNOTE_REVISION="3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"

BREW_BIN="/opt/homebrew/bin/brew"
BREW_PREFIX="/opt/homebrew"
PYTHON_BIN=""

log() { printf '[Kienzledoku Local AI] %s\n' "$*"; }
warn() { printf '[Kienzledoku Local AI] WARNUNG: %s\n' "$*" >&2; }
die() { printf '[Kienzledoku Local AI] FEHLER: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Kienzledoku Local AI – macOS Apple Silicon / M4

Installiert wahlweise einzeln oder kombiniert und M4-beschleunigt:
  - Qwen3.5-9B Q6_K über llama.cpp/Metal, OpenAI-API auf Port 8080
  - Whisper large-v3 über MLX/Metal, Final-Block-API auf Port 8179
  - pyannote Community-1 über PyTorch MPS, API auf Port 8183

Aufruf:
  manager_macos.sh [--action AKTION] [Optionen]

Aktionen:
  install             Installation oder kontrolliertes Upgrade (Standard)
  start               Dienste für diese Anmeldung laden
  stop                Dienste entladen
  restart             Dienste neu laden
  status              launchd- und HTTP-Status anzeigen
  test                Lokale Schnittstellen prüfen
  enable-autostart    Automatisches Laden bei Anmeldung aktivieren
  disable-autostart   Autostart entfernen; aktuell laufende Dienste bleiben aktiv
  uninstall           Nur diese Local-AI-Installation vollständig entfernen
  self-test           Statische, modellfreie Selbsttests ausführen

Installationsoptionen:
  --components ask    Komponenten interaktiv auswählen (Standard)
  --components LISTE  all oder kommasepariert: llm, whisper, pyannote
  --add-components L  Komponenten zu einer Installation hinzufügen, ohne
                      bereits ausgewählte Dienste zu deaktivieren
  --listen-address IP IPv4-Listen-Adresse; Standard interaktiv, empfohlen 127.0.0.1
  --mode ask          Startmodus interaktiv abfragen (Standard)
  --mode autostart    Bei jeder Benutzeranmeldung laden und jetzt starten
  --mode manual       Nur jetzt laden; nach Neuanmeldung nicht automatisch starten
  --no-start          Nach der Installation nicht starten

Weitere Optionen:
  --yes               Rückfrage bei uninstall bestätigen
  --version           Version ausgeben
  -h, --help          Hilfe ausgeben

Voraussetzungen:
  - Apple Silicon (native arm64), empfohlen: Mac mini M4 mit 32 GB
  - Xcode Command Line Tools
  - Apple-Silicon-Homebrew unter /opt/homebrew
  - für pyannote einmalig akzeptierte Community-1-Bedingungen und HF-Lesetoken
EOF
}

while (($#)); do
    case "$1" in
        --action) [[ $# -ge 2 ]] || die "Wert für --action fehlt."; ACTION="$2"; shift 2 ;;
        --mode) [[ $# -ge 2 ]] || die "Wert für --mode fehlt."; MODE="$2"; shift 2 ;;
        --components) [[ $# -ge 2 ]] || die "Wert für --components fehlt."; COMPONENTS_OPTION="$2"; shift 2 ;;
        --add-components) [[ $# -ge 2 ]] || die "Wert für --add-components fehlt."; ADD_COMPONENTS_OPTION="$2"; shift 2 ;;
        --listen-address) [[ $# -ge 2 ]] || die "Wert für --listen-address fehlt."; LISTEN_ADDRESS_OPTION="$2"; shift 2 ;;
        --service) [[ $# -ge 2 ]] || die "Wert für --service fehlt."; SERVICE="$2"; shift 2 ;;
        --no-start) NO_START=1; shift ;;
        --yes) ASSUME_YES=1; shift ;;
        --version) printf '%s\n' "$VERSION"; exit 0 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1" ;;
    esac
done

case "$ACTION" in
    install|start|stop|restart|status|test|enable-autostart|disable-autostart|uninstall|self-test|run-service|set-environment) ;;
    *) die "Unbekannte Aktion: $ACTION" ;;
esac
case "$MODE" in ask|autostart|manual) ;; *) die "--mode erlaubt ask, autostart oder manual." ;; esac
if [[ -n "$ADD_COMPONENTS_OPTION" && "$COMPONENTS_OPTION" != "ask" ]]; then
    die "--components und --add-components dürfen nicht gemeinsam verwendet werden."
fi

component_selected() {
    case ",$SELECTED_COMPONENTS," in
        *",$1,"*) return 0 ;;
        *) return 1 ;;
    esac
}

component_install_requested() {
    case ",$INSTALL_COMPONENTS," in
        *",$1,"*) return 0 ;;
        *) return 1 ;;
    esac
}

load_configuration() {
    local stored
    if [[ -f "$COMPONENTS_FILE" ]]; then
        stored="$(tr -d '[:space:]' < "$COMPONENTS_FILE")"
        [[ -n "$stored" ]] && normalize_components "$stored"
    fi
    if [[ -f "$LISTEN_ADDRESS_FILE" ]]; then
        stored="$(tr -d '[:space:]' < "$LISTEN_ADDRESS_FILE")"
        if [[ -n "$stored" ]]; then
            valid_ipv4 "$stored" || die "Gespeicherte Listen-Adresse ist ungültig: $stored"
            LISTEN_ADDRESS="$stored"
        fi
    fi
}

connection_address() {
    if [[ "$LISTEN_ADDRESS" == "0.0.0.0" ]]; then
        printf '127.0.0.1\n'
    else
        printf '%s\n' "$LISTEN_ADDRESS"
    fi
}

valid_ipv4() {
    local address="$1" part
    local -a parts
    local IFS='.'
    read -r -a parts <<< "$address"
    [[ ${#parts[@]} -eq 4 ]] || return 1
    for part in "${parts[@]}"; do
        [[ "$part" =~ ^[0-9]{1,3}$ ]] || return 1
        (( 10#$part <= 255 )) || return 1
    done
}

normalize_components() {
    local raw item normalized=""
    local -a items
    raw="$(printf '%s' "$1" | /usr/bin/tr '[:upper:]' '[:lower:]' | /usr/bin/tr -d '[:space:]')"
    [[ "$raw" != "all" ]] || raw="llm,whisper,pyannote"
    local IFS=','
    read -r -a items <<< "$raw"
    for item in "${items[@]}"; do
        [[ -n "$item" ]] || continue
        case "$item" in
            1|llm|qwen) item="llm" ;;
            2|asr|whisper) item="asr" ;;
            3|diarization|diarisierung|pyannote) item="diarization" ;;
            *) die "Unbekannte Komponente: $item (erlaubt: llm, whisper, pyannote oder all)." ;;
        esac
        case ",$normalized," in
            *",$item,"*) ;;
            *) normalized="${normalized:+$normalized,}$item" ;;
        esac
    done
    [[ -n "$normalized" ]] || die "Mindestens eine Komponente muss ausgewählt werden."
    SELECTED_COMPONENTS="$normalized"
}

detect_native_macos() {
    local os arch translated hw_arm64
    os="$(uname -s)"
    arch="$(uname -m)"
    [[ "$os" == "Darwin" ]] || die "Dieser Installer unterstützt ausschließlich macOS."
    translated="$(sysctl -in sysctl.proc_translated 2>/dev/null || printf '0')"
    hw_arm64="$(sysctl -in hw.optional.arm64 2>/dev/null || printf '0')"
    if [[ "$arch" == "x86_64" && ( "$translated" == "1" || "$hw_arm64" == "1" ) ]]; then
        [[ "${KIENZLEDOKU_LOCAL_AI_NATIVE_REEXEC:-0}" != "1" ]] || \
            die "Nativer arm64-Neustart ist fehlgeschlagen."
        exec /usr/bin/env KIENZLEDOKU_LOCAL_AI_NATIVE_REEXEC=1 \
            /usr/bin/arch -arm64 /bin/bash "$SCRIPT_PATH" "${ORIGINAL_ARGS[@]}"
    fi
    [[ "$arch" == "arm64" ]] || die "Apple Silicon erforderlich; Prozessarchitektur: $arch"
    [[ "$translated" != "1" ]] || die "Rosetta ist aktiv; native arm64-Ausführung erforderlich."
    [[ "$EUID" -ne 0 ]] || die "Nicht mit sudo/root ausführen."
}

configure_brew() {
    [[ -x "$BREW_BIN" ]] || die \
        "Apple-Silicon-Homebrew fehlt unter /opt/homebrew. Bitte zuerst von https://brew.sh installieren."
    BREW_PREFIX="$($BREW_BIN --prefix)"
    [[ "$BREW_PREFIX" == "/opt/homebrew" ]] || die \
        "Native Apple-Silicon-Homebrew-Installation erwartet; gefunden: $BREW_PREFIX"
    export PATH="$BREW_PREFIX/bin:$BREW_PREFIX/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
}

check_hardware() {
    local memory_bytes available_kb required_kb required_gib
    memory_bytes="$(sysctl -n hw.memsize)"
    if (( memory_bytes < 30000000000 )); then
        die "Mindestens 32 GB Unified Memory werden für Q6_K + Whisper + pyannote empfohlen und hier vorausgesetzt."
    fi
    available_kb="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
    required_gib=2
    component_selected llm && required_gib=$((required_gib + 12))
    component_selected asr && required_gib=$((required_gib + 5))
    component_selected diarization && required_gib=$((required_gib + 6))
    required_kb=$((required_gib * 1024 * 1024))
    if [[ "$available_kb" =~ ^[0-9]+$ ]] && (( available_kb < required_kb )); then
        die "Für die ausgewählten Komponenten werden mindestens $required_gib GiB freier Speicher benötigt."
    fi
    log "Hardwareprofil: native arm64, mindestens 32 GB Unified Memory, Metal/MPS ohne CPU-Fallback."
    log "Ausgewählte Komponenten: $SELECTED_COMPONENTS; Speicherreserve: $required_gib GiB."
}

install_dependencies() {
    local formula
    local -a formulas=(python@3.12)
    command -v xcode-select >/dev/null 2>&1 || die "xcode-select fehlt."
    xcode-select -p >/dev/null 2>&1 || die \
        "Xcode Command Line Tools fehlen. Zuerst ausführen: xcode-select --install"
    if component_selected llm; then
        formulas+=(cmake ninja)
    fi
    if component_selected asr || component_selected diarization; then
        formulas+=(ffmpeg)
    fi
    for formula in "${formulas[@]}"; do
        if ! "$BREW_BIN" list --versions "$formula" >/dev/null 2>&1; then
            log "Installiere Homebrew-Abhängigkeit: $formula"
            "$BREW_BIN" install "$formula"
        fi
    done
    PYTHON_BIN="$($BREW_BIN --prefix python@3.12)/bin/python3.12"
    [[ -x "$PYTHON_BIN" ]] || die "Homebrew Python 3.12 wurde nicht gefunden."
    "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' || \
        die "Python 3.12 erforderlich: $PYTHON_BIN"
}

resolve_python() {
    if [[ -x "$($BREW_BIN --prefix python@3.12 2>/dev/null || true)/bin/python3.12" ]]; then
        PYTHON_BIN="$($BREW_BIN --prefix python@3.12)/bin/python3.12"
    elif [[ -x /opt/homebrew/opt/python@3.12/bin/python3.12 ]]; then
        PYTHON_BIN="/opt/homebrew/opt/python@3.12/bin/python3.12"
    else
        PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
    fi
    [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || die "Python wurde nicht gefunden."
}

sha256_file() { /usr/bin/shasum -a 256 "$1" | awk '{print $1}'; }

ensure_dirs() {
    mkdir -p "$BIN_DIR" "$SCRIPT_INSTALL_DIR" "$MODEL_DIR" "$PYTHON_DIR" \
        "$SOURCE_DIR" "$PLIST_STORE" "$LOG_DIR" "$USER_PLIST_DIR"
    chmod 700 "$INSTALL_ROOT" "$BIN_DIR" "$SCRIPT_INSTALL_DIR" "$MODEL_DIR" \
        "$PYTHON_DIR" "$SOURCE_DIR" "$PLIST_STORE" "$LOG_DIR"
    local log_file
    for log_file in llm.log llm.error.log asr.log asr.error.log diarization.log diarization.error.log environment.log environment.error.log; do
        touch "$LOG_DIR/$log_file"
        chmod 600 "$LOG_DIR/$log_file"
    done
}

copy_runtime_sources() {
    local asr_source="$SCRIPT_DIR/asr_server_mlx.py"
    local diar_source="$SCRIPT_DIR/diarization_server_mps.py"
    [[ -f "$asr_source" ]] || asr_source="$SCRIPT_INSTALL_DIR/asr_server_mlx.py"
    [[ -f "$diar_source" ]] || diar_source="$SCRIPT_INSTALL_DIR/diarization_server_mps.py"
    if component_selected asr; then
        [[ -f "$asr_source" ]] || die "ASR-Server-Quelldatei fehlt neben dem Installer."
        install -m 700 "$asr_source" "$SCRIPT_INSTALL_DIR/asr_server_mlx.py"
    fi
    if component_selected diarization; then
        [[ -f "$diar_source" ]] || die "Diarisierungs-Server-Quelldatei fehlt neben dem Installer."
        install -m 700 "$diar_source" "$SCRIPT_INSTALL_DIR/diarization_server_mps.py"
    fi
    if [[ "$SCRIPT_PATH" != "$MANAGER_INSTALL_PATH" ]]; then
        install -m 700 "$SCRIPT_PATH" "$MANAGER_INSTALL_PATH"
    fi
}

write_versions() {
    cat > "$VERSIONS_FILE" <<EOF
INSTALLER_VERSION=$VERSION
LLAMA_CPP_BUILD=$LLAMA_BUILD
LLAMA_CPP_REF=$LLAMA_REF
QWEN_REPOSITORY=$QWEN_REPOSITORY
QWEN_REVISION=$QWEN_REVISION
QWEN_FILENAME=$QWEN_FILENAME
QWEN_SIZE=$QWEN_SIZE
QWEN_SHA256=$QWEN_SHA256
MLX_VERSION=$MLX_VERSION
MLX_WHISPER_VERSION=$MLX_WHISPER_VERSION
WHISPER_REPOSITORY=$WHISPER_REPOSITORY
WHISPER_REVISION=$WHISPER_REVISION
WHISPER_WEIGHTS_SHA256=$WHISPER_WEIGHTS_SHA256
WHISPER_CONFIG_SHA256=$WHISPER_CONFIG_SHA256
PYANNOTE_AUDIO_VERSION=$PYANNOTE_AUDIO_VERSION
PYANNOTE_REPOSITORY=$PYANNOTE_REPOSITORY
PYANNOTE_REVISION=$PYANNOTE_REVISION
EOF
    chmod 600 "$VERSIONS_FILE"
}

save_configuration() {
    printf '%s\n' "$SELECTED_COMPONENTS" > "$COMPONENTS_FILE"
    printf '%s\n' "$LISTEN_ADDRESS" > "$LISTEN_ADDRESS_FILE"
    chmod 600 "$COMPONENTS_FILE" "$LISTEN_ADDRESS_FILE"
}

download_verified() {
    local url="$1" destination="$2" expected="$3" part actual
    if [[ -f "$destination" ]]; then
        actual="$(sha256_file "$destination")"
        if [[ "$actual" == "$expected" ]]; then
            log "Bereits vollständig und geprüft: $(basename "$destination")"
            return
        fi
        warn "Vorhandene Datei hat eine abweichende Prüfsumme; sie wird erst nach erfolgreichem Ersatz überschrieben."
    fi
    part="${destination}.part"
    log "Lade $(basename "$destination") ..."
    /usr/bin/curl --fail --location --retry 5 --retry-all-errors --continue-at - \
        --output "$part" "$url"
    actual="$(sha256_file "$part")"
    [[ "$actual" == "$expected" ]] || {
        rm -f "$part"
        die "SHA-256-Prüfung fehlgeschlagen: $(basename "$destination")"
    }
    mv -f "$part" "$destination"
    chmod 600 "$destination"
}

find_local_llama_source() {
    local candidate
    local -a candidates=()
    if [[ -n "${KIENZLEDOKU_LLAMA_SOURCE:-}" ]]; then
        candidates+=("$KIENZLEDOKU_LLAMA_SOURCE")
    fi
    candidates+=(
        "$SCRIPT_DIR/../../kienzlefon-ai/system-snapshots/3090-20260824T222010Z/files/opt/kienzlefon-ai/src/llama.cpp"
        "$SCRIPT_DIR/../../../kienzlefon-ai/system-snapshots/3090-20260824T222010Z/files/opt/kienzlefon-ai/src/llama.cpp"
    )
    for candidate in "${candidates[@]}"; do
        if [[ -d "$candidate/.git" ]] && \
            [[ "$(git -C "$candidate" rev-parse HEAD 2>/dev/null || true)" == "$LLAMA_REF" ]]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
}

build_llama_cpp() {
    local source="$SOURCE_DIR/llama.cpp" build="$SOURCE_DIR/llama.cpp/build-kienzledoku-metal"
    local local_source jobs commit device_list
    local_source="$(find_local_llama_source || true)"
    if [[ ! -d "$source/.git" ]]; then
        if [[ -n "$local_source" ]]; then
            log "Übernehme den exakt verwendeten llama.cpp-Stand aus dem lokalen Kienzlefon-Snapshot."
            git clone --local --no-hardlinks "$local_source" "$source"
        else
            log "Lade llama.cpp aus dem offiziellen Repository."
            git clone --filter=blob:none "$LLAMA_REPOSITORY" "$source"
        fi
    else
        [[ -z "$(git -C "$source" status --porcelain --untracked-files=no)" ]] || \
            die "Lokale Änderungen im verwalteten llama.cpp-Quellbaum: $source"
    fi
    if ! git -C "$source" cat-file -e "${LLAMA_REF}^{commit}" 2>/dev/null; then
        git -C "$source" fetch --force origin "$LLAMA_REF"
    fi
    git -C "$source" checkout --detach "$LLAMA_REF"
    commit="$(git -C "$source" rev-parse HEAD)"
    [[ "$commit" == "$LLAMA_REF" ]] || die "Unerwarteter llama.cpp-Commit: $commit"

    cmake -S "$source" -B "$build" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_METAL=ON \
        -DGGML_METAL_EMBED_LIBRARY=ON \
        -DGGML_NATIVE=ON \
        -DLLAMA_OPENSSL=OFF \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_TOOLS=ON
    jobs="$(sysctl -n hw.logicalcpu)"
    cmake --build "$build" --target llama-server llama-cli -j "$jobs"
    ln -sfn "$build/bin/llama-server" "$BIN_DIR/llama-server"
    ln -sfn "$build/bin/llama-cli" "$BIN_DIR/llama-cli"
    file -L "$BIN_DIR/llama-server" | grep -q 'arm64' || die "llama-server ist nicht arm64."
    grep -Eq '^GGML_METAL:BOOL=ON$' "$build/CMakeCache.txt" || die "Metal-Build fehlt."
    device_list="$("$BIN_DIR/llama-cli" --list-devices 2>&1)" || die \
        "llama.cpp konnte die Geräteliste nicht abfragen."
    printf '%s\n' "$device_list"
    printf '%s\n' "$device_list" | grep -Eq '^[[:space:]]+MTL[0-9]+:' || die \
        "llama.cpp erkennt kein MTL-Gerät; kein CPU-Fallback."
    log "llama.cpp Metal-Gerät erkannt: $(printf '%s\n' "$device_list" | awk '/^[[:space:]]+MTL[0-9]+:/ { sub(/^[[:space:]]+/, ""); print; exit }')"
}

find_local_qwen() {
    local candidate
    if [[ -n "${KIENZLEDOKU_Q6_SOURCE:-}" && -f "${KIENZLEDOKU_Q6_SOURCE}" ]]; then
        printf '%s\n' "$KIENZLEDOKU_Q6_SOURCE"
        return
    fi
    for candidate in \
        "$SCRIPT_DIR/../../kienzlefon-ai/system-snapshots/3090-runtime-20260825T084106Z/files/opt/kienzlefon-ai/models/$QWEN_FILENAME" \
        "$SCRIPT_DIR/../../../kienzlefon-ai/system-snapshots/3090-runtime-20260825T084106Z/files/opt/kienzlefon-ai/models/$QWEN_FILENAME"
    do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
}

install_qwen_model() {
    local destination="$MODEL_DIR/$QWEN_FILENAME" local_model actual part size
    if [[ -f "$destination" ]]; then
        size="$(stat -f '%z' "$destination")"
        if [[ "$size" == "$QWEN_SIZE" && "$(sha256_file "$destination")" == "$QWEN_SHA256" ]]; then
            log "Qwen3.5-9B Q6_K ist bereits lokal und geprüft."
            return
        fi
    fi
    local_model="$(find_local_qwen || true)"
    if [[ -n "$local_model" ]]; then
        size="$(stat -f '%z' "$local_model")"
        [[ "$size" == "$QWEN_SIZE" ]] || die "Lokale Q6_K-Quelldatei hat eine unerwartete Größe."
        log "Prüfe die vorhandene produktive Q6_K-Snapshot-Kopie ..."
        actual="$(sha256_file "$local_model")"
        [[ "$actual" == "$QWEN_SHA256" ]] || die "Lokale Q6_K-Snapshot-Kopie hat eine falsche Prüfsumme."
        part="${destination}.part"
        rm -f "$part"
        log "Kopiere Qwen3.5-9B Q6_K in den lokalen Modellspeicher ..."
        if ! cp -c "$local_model" "$part" 2>/dev/null; then
            cp "$local_model" "$part"
        fi
        [[ "$(sha256_file "$part")" == "$QWEN_SHA256" ]] || {
            rm -f "$part"
            die "Q6_K-Prüfsumme nach dem Kopieren stimmt nicht."
        }
        mv -f "$part" "$destination"
        chmod 600 "$destination"
        return
    fi
    download_verified \
        "https://huggingface.co/$QWEN_REPOSITORY/resolve/$QWEN_REVISION/$QWEN_FILENAME?download=true" \
        "$destination" "$QWEN_SHA256"
    [[ "$(stat -f '%z' "$destination")" == "$QWEN_SIZE" ]] || die "Q6_K-Dateigröße stimmt nicht."
}

install_asr() {
    local venv="$PYTHON_DIR/asr-venv" model="$MODEL_DIR/whisper-large-v3-mlx"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
    "$venv/bin/python" -m pip install "mlx==$MLX_VERSION" "mlx-whisper==$MLX_WHISPER_VERSION"
    "$venv/bin/python" - <<PY
import importlib.metadata
assert importlib.metadata.version("mlx") == "$MLX_VERSION"
assert importlib.metadata.version("mlx-whisper") == "$MLX_WHISPER_VERSION"
import mlx.core as mx
if not mx.metal.is_available():
    raise SystemExit("MLX Metal ist nicht verfügbar; kein CPU-Fallback")
x = mx.arange(32, dtype=mx.float32)
mx.eval((x * x).sum())
print("MLX/Metal:", mx.metal.device_info())
PY
    mkdir -p "$model"
    download_verified \
        "https://huggingface.co/$WHISPER_REPOSITORY/resolve/$WHISPER_REVISION/$WHISPER_WEIGHTS?download=true" \
        "$model/$WHISPER_WEIGHTS" "$WHISPER_WEIGHTS_SHA256"
    download_verified \
        "https://huggingface.co/$WHISPER_REPOSITORY/resolve/$WHISPER_REVISION/$WHISPER_CONFIG?download=true" \
        "$model/$WHISPER_CONFIG" "$WHISPER_CONFIG_SHA256"
}

install_pyannote() {
    local venv="$PYTHON_DIR/diarization-venv"
    local model="$MODEL_DIR/pyannote-speaker-diarization-community-1"
    local marker="$model/.kienzledoku-revision"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
    "$venv/bin/python" -m pip install "pyannote.audio==$PYANNOTE_AUDIO_VERSION"
    "$venv/bin/python" - <<PY
import importlib.metadata
import torch
assert importlib.metadata.version("pyannote.audio") == "$PYANNOTE_AUDIO_VERSION"
if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
    raise SystemExit("PyTorch MPS ist nicht verfügbar; kein CPU-Fallback")
print("PyTorch:", torch.__version__, "| MPS verfügbar")
PY

    if [[ -f "$marker" ]] && [[ "$(cat "$marker")" == "$PYANNOTE_REVISION" ]]; then
        log "pyannote Community-1 ist bereits als feste lokale Revision vorhanden."
        return
    fi
    mkdir -p "$model"
    log "pyannote Community-1 ist zugriffsgeschützt."
    log "Bitte vorher im selben Hugging-Face-Konto die Bedingungen akzeptieren:"
    log "https://huggingface.co/$PYANNOTE_REPOSITORY"
    PYANNOTE_MODEL_DIR="$model" \
    PYANNOTE_REPOSITORY="$PYANNOTE_REPOSITORY" \
    PYANNOTE_REVISION="$PYANNOTE_REVISION" \
    HF_HOME="$MODEL_DIR/huggingface-cache" \
    "$venv/bin/python" - <<'PY'
import getpass
import os
from pathlib import Path
from huggingface_hub import snapshot_download

token = getpass.getpass("Hugging-Face-Lesetoken (Eingabe bleibt unsichtbar): ").strip()
if not token:
    raise SystemExit("FEHLER: leerer Hugging-Face-Token")
target = Path(os.environ["PYANNOTE_MODEL_DIR"])
snapshot_download(
    repo_id=os.environ["PYANNOTE_REPOSITORY"],
    revision=os.environ["PYANNOTE_REVISION"],
    local_dir=str(target),
    token=token,
)
del token
(target / ".kienzledoku-revision").write_text(
    os.environ["PYANNOTE_REVISION"] + "\n", encoding="ascii"
)
print("pyannote Community-1 wurde lokal gespeichert; der Token wurde nicht persistiert.")
PY
    chmod -R u+rwX,go-rwx "$model" "$MODEL_DIR/huggingface-cache" 2>/dev/null || true
}

write_launch_agents() {
    rm -f "$PLIST_STORE"/*.plist
    KIENZLEDOKU_PLIST_STORE="$PLIST_STORE" \
    KIENZLEDOKU_MANAGER="$MANAGER_INSTALL_PATH" \
    KIENZLEDOKU_LOG_DIR="$LOG_DIR" \
    KIENZLEDOKU_INSTALL_ROOT="$INSTALL_ROOT" \
    KIENZLEDOKU_COMPONENTS="$SELECTED_COMPONENTS" \
    KIENZLEDOKU_PATH="$BREW_PREFIX/bin:$BREW_PREFIX/sbin:/usr/bin:/bin:/usr/sbin:/sbin" \
    "$PYTHON_BIN" - <<'PY'
import os
import plistlib
from pathlib import Path

store = Path(os.environ["KIENZLEDOKU_PLIST_STORE"])
manager = os.environ["KIENZLEDOKU_MANAGER"]
logs = Path(os.environ["KIENZLEDOKU_LOG_DIR"])
root = os.environ["KIENZLEDOKU_INSTALL_ROOT"]
path = os.environ["KIENZLEDOKU_PATH"]
selected = set(os.environ["KIENZLEDOKU_COMPONENTS"].split(","))

services = {
    "llm": "de.kienzledoku.local-ai.llm",
    "asr": "de.kienzledoku.local-ai.asr",
    "diarization": "de.kienzledoku.local-ai.diarization",
}
for role, label in services.items():
    if role not in selected:
        continue
    env = {"PATH": path, "PYTHONUNBUFFERED": "1"}
    if role == "diarization":
        env.update({"HF_HUB_OFFLINE": "1", "PYTORCH_ENABLE_MPS_FALLBACK": "0"})
    payload = {
        "Label": label,
        "ProgramArguments": [manager, "--action", "run-service", "--service", role],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "WorkingDirectory": root,
        "EnvironmentVariables": env,
        "StandardOutPath": str(logs / f"{role}.log"),
        "StandardErrorPath": str(logs / f"{role}.error.log"),
    }
    with (store / f"{label}.plist").open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)

label = "de.kienzledoku.local-ai.environment"
payload = {
    "Label": label,
    "ProgramArguments": [manager, "--action", "set-environment"],
    "RunAtLoad": True,
    "ProcessType": "Interactive",
    "WorkingDirectory": root,
    "EnvironmentVariables": {"PATH": path},
    "StandardOutPath": str(logs / "environment.log"),
    "StandardErrorPath": str(logs / "environment.error.log"),
}
with (store / f"{label}.plist").open("wb") as handle:
    plistlib.dump(payload, handle, sort_keys=True)
PY
    chmod 600 "$PLIST_STORE"/*.plist
}

plist_path() { printf '%s/%s.plist\n' "$PLIST_STORE" "$1"; }
installed_plist_path() { printf '%s/%s.plist\n' "$USER_PLIST_DIR" "$1"; }

enable_autostart() {
    local label source destination
    load_configuration
    [[ -d "$PLIST_STORE" ]] || die "Zuerst installieren."
    mkdir -p "$USER_PLIST_DIR"
    for label in "$LLM_LABEL" "$ASR_LABEL" "$DIARIZATION_LABEL" "$ENVIRONMENT_LABEL"; do
        rm -f "$(installed_plist_path "$label")"
    done
    for label in "$LLM_LABEL" "$ASR_LABEL" "$DIARIZATION_LABEL" "$ENVIRONMENT_LABEL"; do
        if [[ "$label" == "$LLM_LABEL" ]] && ! component_selected llm; then continue; fi
        if [[ "$label" == "$ASR_LABEL" ]] && ! component_selected asr; then continue; fi
        if [[ "$label" == "$DIARIZATION_LABEL" ]] && ! component_selected diarization; then continue; fi
        source="$(plist_path "$label")"
        destination="$(installed_plist_path "$label")"
        [[ -f "$source" ]] || die "LaunchAgent-Vorlage fehlt: $source"
        install -m 600 "$source" "$destination"
    done
    printf 'autostart\n' > "$MODE_FILE"
    chmod 600 "$MODE_FILE"
    log "Automatisches Laden bei Benutzeranmeldung ist aktiviert."
}

disable_autostart() {
    local label
    for label in "$LLM_LABEL" "$ASR_LABEL" "$DIARIZATION_LABEL" "$ENVIRONMENT_LABEL"; do
        rm -f "$(installed_plist_path "$label")"
    done
    if [[ -d "$INSTALL_ROOT" ]]; then
        printf 'manual\n' > "$MODE_FILE"
        chmod 600 "$MODE_FILE"
    fi
    log "Autostart ist deaktiviert. Bereits geladene Dienste bleiben bis stop oder Abmeldung aktiv."
}

set_kienzledoku_environment() {
    local client_address
    load_configuration
    client_address="$(connection_address)"
    if component_selected asr; then
        /bin/launchctl setenv KIENZLEDOKU_ASR_URL "http://$client_address:$ASR_PORT"
    else
        /bin/launchctl unsetenv KIENZLEDOKU_ASR_URL 2>/dev/null || true
    fi
    if component_selected diarization; then
        /bin/launchctl setenv KIENZLEDOKU_DIARIZATION_URL "http://$client_address:$DIARIZATION_PORT"
    else
        /bin/launchctl unsetenv KIENZLEDOKU_DIARIZATION_URL 2>/dev/null || true
    fi
    if component_selected llm; then
        /bin/launchctl setenv KIENZLEDOKU_LLM_URL "http://$client_address:$LLM_PORT"
    else
        /bin/launchctl unsetenv KIENZLEDOKU_LLM_URL 2>/dev/null || true
    fi
    log "Kienzledoku-Endpunkte der installierten Komponenten auf $client_address gesetzt."
}

unset_kienzledoku_environment() {
    /bin/launchctl unsetenv KIENZLEDOKU_ASR_URL 2>/dev/null || true
    /bin/launchctl unsetenv KIENZLEDOKU_DIARIZATION_URL 2>/dev/null || true
    /bin/launchctl unsetenv KIENZLEDOKU_LLM_URL 2>/dev/null || true
}

launchd_loaded() {
    /bin/launchctl print "gui/$(id -u)/$1" >/dev/null 2>&1
}

bootstrap_service() {
    local label="$1" plist
    if [[ -f "$(installed_plist_path "$label")" ]]; then
        plist="$(installed_plist_path "$label")"
    else
        plist="$(plist_path "$label")"
    fi
    [[ -f "$plist" ]] || die "LaunchAgent fehlt: $plist"
    if launchd_loaded "$label"; then
        /bin/launchctl kickstart -k "gui/$(id -u)/$label"
    else
        /bin/launchctl bootstrap "gui/$(id -u)" "$plist"
    fi
}

start_services() {
    load_configuration
    [[ -x "$MANAGER_INSTALL_PATH" ]] || die "Local AI ist nicht installiert."
    set_kienzledoku_environment
    component_selected llm && bootstrap_service "$LLM_LABEL"
    component_selected asr && bootstrap_service "$ASR_LABEL"
    component_selected diarization && bootstrap_service "$DIARIZATION_LABEL"
    log "Ausgewählte Modelldienste werden in der Reihenfolge LLM → Whisper → pyannote resident geladen."
    log "Status: $MANAGER_INSTALL_PATH --action status"
}

stop_services() {
    local label
    for label in "$DIARIZATION_LABEL" "$ASR_LABEL" "$LLM_LABEL" "$ENVIRONMENT_LABEL"; do
        if launchd_loaded "$label"; then
            /bin/launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || \
                /bin/launchctl remove "$label" 2>/dev/null || true
        fi
    done
    unset_kienzledoku_environment
    log "Modelldienste sind entladen."
}

wait_http() {
    local url="$1" description="$2" attempts="${3:-180}" i
    i=1
    while (( i <= attempts )); do
        if /usr/bin/curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            return
        fi
        sleep 2
        i=$((i + 1))
    done
    die "$description wurde nicht rechtzeitig bereit."
}

run_service() {
    local client_address
    load_configuration
    client_address="$(connection_address)"
    case "$SERVICE" in
        llm)
            component_selected llm || die "LLM ist in dieser Installation nicht ausgewählt."
            [[ -x "$BIN_DIR/llama-server" ]] || die "llama-server fehlt."
            [[ -f "$MODEL_DIR/$QWEN_FILENAME" ]] || die "Q6_K-Modell fehlt."
            exec "$BIN_DIR/llama-server" \
                --model "$MODEL_DIR/$QWEN_FILENAME" \
                --alias qwen3.5-9b \
                --device MTL0 \
                --host "$LISTEN_ADDRESS" \
                --port "$LLM_PORT" \
                --parallel 1 \
                --ctx-size 32768 \
                --n-gpu-layers 999 \
                --reasoning off \
                --reasoning-format deepseek \
                --chat-template-kwargs '{"enable_thinking":false}' \
                --no-mmproj \
                --jinja \
                --log-verbosity 2 \
                --cont-batching
            ;;
        asr)
            component_selected asr || die "Whisper ist in dieser Installation nicht ausgewählt."
            if component_selected llm; then
                wait_http "http://$client_address:$LLM_PORT/health" "Q6_K-LLM" 180
            fi
            export KIENZLEDOKU_ASR_HOST="$LISTEN_ADDRESS"
            export KIENZLEDOKU_ASR_PORT="$ASR_PORT"
            export KIENZLEDOKU_WHISPER_MODEL="$MODEL_DIR/whisper-large-v3-mlx"
            exec "$PYTHON_DIR/asr-venv/bin/python" "$SCRIPT_INSTALL_DIR/asr_server_mlx.py"
            ;;
        diarization)
            component_selected diarization || die "pyannote ist in dieser Installation nicht ausgewählt."
            if component_selected asr; then
                wait_http "http://$client_address:$ASR_PORT/health" "Whisper-large-v3-ASR" 180
            elif component_selected llm; then
                wait_http "http://$client_address:$LLM_PORT/health" "Q6_K-LLM" 180
            fi
            export HF_HUB_OFFLINE=1
            export PYTORCH_ENABLE_MPS_FALLBACK=0
            export KIENZLEDOKU_DIARIZATION_HOST="$LISTEN_ADDRESS"
            export KIENZLEDOKU_DIARIZATION_PORT="$DIARIZATION_PORT"
            export KIENZLEDOKU_PYANNOTE_MODEL="$MODEL_DIR/pyannote-speaker-diarization-community-1"
            exec "$PYTHON_DIR/diarization-venv/bin/python" \
                "$SCRIPT_INSTALL_DIR/diarization_server_mps.py"
            ;;
        *) die "Unbekannter Dienst für run-service: $SERVICE" ;;
    esac
}

status_services() {
    local label endpoint name loaded http_state overall client_address component
    load_configuration
    client_address="$(connection_address)"
    overall=0
    for label in "$LLM_LABEL" "$ASR_LABEL" "$DIARIZATION_LABEL"; do
        case "$label" in
            "$LLM_LABEL") name="LLM Q6_K"; component="llm"; endpoint="http://$client_address:$LLM_PORT/health" ;;
            "$ASR_LABEL") name="Whisper large-v3"; component="asr"; endpoint="http://$client_address:$ASR_PORT/health" ;;
            *) name="pyannote Community-1"; component="diarization"; endpoint="http://$client_address:$DIARIZATION_PORT/health" ;;
        esac
        if ! component_selected "$component"; then
            printf '%-25s nicht installiert/ausgewählt\n' "$name"
            continue
        fi
        if launchd_loaded "$label"; then loaded="geladen"; else loaded="nicht geladen"; overall=1; fi
        if /usr/bin/curl -fsS --max-time 3 "$endpoint" >/dev/null 2>&1; then
            http_state="bereit"
        else
            http_state="nicht bereit"
            overall=1
        fi
        printf '%-25s launchd: %-14s API: %s\n' "$name" "$loaded" "$http_state"
    done
    if [[ -f "$MODE_FILE" ]]; then
        printf 'Startmodus: %s\n' "$(cat "$MODE_FILE")"
    else
        printf 'Startmodus: nicht installiert\n'
    fi
    printf 'Listen-Adresse: %s (lokaler Prüfendpunkt: %s)\n' "$LISTEN_ADDRESS" "$client_address"
    return "$overall"
}

test_services() {
    local llm='{}' asr='{}' asr_inference='{}' diar='{}' client_address
    local test_dir test_wav test_response
    load_configuration
    client_address="$(connection_address)"
    resolve_python
    if component_selected llm; then
        llm="$(/usr/bin/curl -fsS --max-time 10 "http://$client_address:$LLM_PORT/v1/models")" || \
            die "LLM /v1/models nicht erreichbar."
    fi
    if component_selected asr; then
        asr="$(/usr/bin/curl -fsS --max-time 10 "http://$client_address:$ASR_PORT/health")" || \
            die "ASR /health nicht erreichbar."
        test_dir="$(mktemp -d "${TMPDIR:-/tmp}/kienzledoku-asr-test.XXXXXX")"
        test_wav="$test_dir/test.wav"
        test_response="$test_dir/response.json"
        "$PYTHON_BIN" - "$test_wav" <<'PY'
import math
import struct
import sys
import wave

rate = 16000
with wave.open(sys.argv[1], "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(rate)
    output.writeframes(
        b"".join(
            struct.pack("<h", int(1800 * math.sin(2 * math.pi * 440 * index / rate)))
            for index in range(rate)
        )
    )
PY
        if ! /usr/bin/curl -fsS --max-time 180 \
            --output "$test_response" \
            -F "file=@$test_wav;type=audio/wav" \
            -F "language=de" \
            "http://$client_address:$ASR_PORT/v1/asr/final-block"; then
            rm -f "$test_wav" "$test_response"
            rmdir "$test_dir" 2>/dev/null || true
            die "ASR-Transkriptionsprobe ist fehlgeschlagen."
        fi
        asr_inference="$(cat "$test_response")"
        rm -f "$test_wav" "$test_response"
        rmdir "$test_dir" 2>/dev/null || true
    fi
    if component_selected diarization; then
        diar="$(/usr/bin/curl -fsS --max-time 10 "http://$client_address:$DIARIZATION_PORT/health")" || \
            die "Diarisierung /health nicht erreichbar."
    fi
    KIENZLEDOKU_COMPONENTS="$SELECTED_COMPONENTS" \
    LLM_JSON="$llm" ASR_JSON="$asr" ASR_INFERENCE_JSON="$asr_inference" \
    DIAR_JSON="$diar" "$PYTHON_BIN" - <<'PY'
import json, os
llm = json.loads(os.environ["LLM_JSON"])
asr = json.loads(os.environ["ASR_JSON"])
asr_inference = json.loads(os.environ["ASR_INFERENCE_JSON"])
diar = json.loads(os.environ["DIAR_JSON"])
selected = set(os.environ["KIENZLEDOKU_COMPONENTS"].split(","))
if "llm" in selected:
    ids = [item.get("id") for item in llm.get("data", [])]
    assert "qwen3.5-9b" in ids, ids
if "asr" in selected:
    assert asr.get("ok") is True and asr.get("device") == "metal" and asr.get("resident") is True
    assert asr_inference.get("device") == "metal", asr_inference
    assert asr_inference.get("decoder") == "mlx-whisper-large-v3", asr_inference
    assert abs(float(asr_inference.get("duration")) - 1.0) < 0.01, asr_inference
if "diarization" in selected:
    assert diar.get("ok") is True and diar.get("device") == "mps" and diar.get("resident") is True
print("API-Verträge, Hardwaregeräte und ASR-Transkriptionsprobe sind korrekt.")
PY
    log "Schnittstellentest erfolgreich."
}

choose_mode() {
    local answer stored_mode
    if [[ "$MODE" != "ask" ]]; then return; fi
    if [[ -n "$ADD_COMPONENTS_OPTION" && -f "$MODE_FILE" ]]; then
        stored_mode="$(tr -d '[:space:]' < "$MODE_FILE")"
        case "$stored_mode" in
            autostart|manual)
                MODE="$stored_mode"
                log "Vorhandener Startmodus bleibt erhalten: $MODE."
                return
                ;;
        esac
    fi
    [[ -t 0 ]] || die "Ohne interaktives Terminal bitte --mode autostart oder --mode manual angeben."
    printf '\nWie sollen die ausgewählten Modelle geladen werden?\n'
    printf '  1) Automatisch bei jeder macOS-Anmeldung und jetzt laden\n'
    printf '  2) Nur jetzt laden; später manuell über Startskript (Standard)\n'
    printf 'Auswahl [1/2]: '
    IFS= read -r answer
    case "$answer" in
        1) MODE="autostart" ;;
        ""|2) MODE="manual" ;;
        *) die "Ungültige Auswahl." ;;
    esac
}

choose_components() {
    local answer existing requested
    load_configuration
    if [[ -n "$ADD_COMPONENTS_OPTION" ]]; then
        existing=""
        if [[ -f "$COMPONENTS_FILE" ]]; then
            existing="$(tr -d '[:space:]' < "$COMPONENTS_FILE")"
        fi
        normalize_components "$ADD_COMPONENTS_OPTION"
        requested="$SELECTED_COMPONENTS"
        normalize_components "${existing:+$existing,}$requested"
        INSTALL_COMPONENTS="$requested"
        log "Zusätzliche Komponenten: $INSTALL_COMPONENTS; danach aktiv: $SELECTED_COMPONENTS."
        return
    fi
    if [[ "$COMPONENTS_OPTION" != "ask" ]]; then
        normalize_components "$COMPONENTS_OPTION"
        INSTALL_COMPONENTS="$SELECTED_COMPONENTS"
        return
    fi
    [[ -t 0 ]] || die "Ohne interaktives Terminal bitte --components all oder eine Komponentenliste angeben."
    printf '\nWelche Komponenten sollen lokal installiert und aktiviert werden?\n'
    printf '  1) LLM: Qwen3.5-9B Q6_K (Port %s)\n' "$LLM_PORT"
    printf '  2) Spracherkennung: Whisper large-v3 (Port %s)\n' "$ASR_PORT"
    printf '  3) Sprechertrennung: pyannote Community-1 (Port %s)\n' "$DIARIZATION_PORT"
    printf 'Mehrere Einträge mit Komma wählen, z. B. 1,3.\n'
    printf 'Auswahl [%s]: ' "$SELECTED_COMPONENTS"
    IFS= read -r answer
    [[ -n "$answer" ]] || answer="$SELECTED_COMPONENTS"
    normalize_components "$answer"
    INSTALL_COMPONENTS="$SELECTED_COMPONENTS"
}

choose_listen_address() {
    local answer confirmation interactive_choice=0
    if [[ "$LISTEN_ADDRESS_OPTION" != "ask" ]]; then
        answer="$LISTEN_ADDRESS_OPTION"
    else
        [[ -t 0 ]] || die "Ohne interaktives Terminal bitte --listen-address angeben."
        interactive_choice=1
        printf '\nAn welcher IPv4-Adresse sollen die ausgewählten Dienste lauschen?\n'
        printf '  127.0.0.1 = nur dieser Mac (sicherer Standard)\n'
        printf '  0.0.0.0   = alle IPs/Netzwerkschnittstellen dieses Macs\n'
        printf '  andere IP = nur die Netzwerkschnittstelle mit genau dieser Adresse\n'
        printf 'Listen-Adresse [%s]: ' "$LISTEN_ADDRESS"
        IFS= read -r answer
        [[ -n "$answer" ]] || answer="$LISTEN_ADDRESS"
    fi
    valid_ipv4 "$answer" || die "Ungültige IPv4-Listen-Adresse: $answer"
    LISTEN_ADDRESS="$answer"
    if [[ "$LISTEN_ADDRESS" == "0.0.0.0" ]]; then
        warn "0.0.0.0 gibt die APIs auf allen IPs dieses Macs frei; sie besitzen keine Authentifizierung."
        if (( interactive_choice == 1 )); then
            printf 'Wirklich für andere Geräte im Netzwerk freigeben? [j/N]: '
            IFS= read -r confirmation
            case "$confirmation" in j|J|ja|JA|Ja) ;; *) die "Netzwerkfreigabe abgebrochen." ;; esac
        fi
    elif [[ "$LISTEN_ADDRESS" != 127.* ]]; then
        warn "$LISTEN_ADDRESS ist keine Loopback-Adresse; die APIs besitzen keine Authentifizierung."
    fi
}

install_action() {
    detect_native_macos
    configure_brew
    choose_components
    choose_listen_address
    choose_mode
    check_hardware
    install_dependencies
    ensure_dirs
    if [[ -x "$MANAGER_INSTALL_PATH" ]]; then
        stop_services || true
    fi
    copy_runtime_sources
    write_versions
    save_configuration

    if component_install_requested llm; then
        log "Installiere identischen Qwen3.5-9B-Q6_K-Modellstand und Metal-Runtime."
        build_llama_cpp
        install_qwen_model
    fi
    if component_install_requested asr; then
        log "Installiere Whisper large-v3 mit MLX/Metal."
        install_asr
    fi
    if component_install_requested diarization; then
        log "Installiere pyannote Community-1 mit PyTorch MPS."
        install_pyannote
    fi
    write_launch_agents

    if [[ "$MODE" == "autostart" ]]; then
        enable_autostart
    else
        disable_autostart
    fi
    if (( NO_START == 0 )); then
        start_services
    fi
    log "Installation abgeschlossen: $INSTALL_ROOT"
    log "Listen-Adresse: $LISTEN_ADDRESS; aktive Komponenten: $SELECTED_COMPONENTS."
    log "Kienzledoku verwendet bei künftigem Start nur die ausgewählten lokalen Endpunkte."
}

uninstall_action() {
    local answer
    detect_native_macos
    if (( ASSUME_YES == 0 )); then
        [[ -t 0 ]] || die "Ohne Terminal erfordert uninstall die Option --yes."
        printf 'Kienzledoku Local AI einschließlich lokaler Modelle vollständig entfernen? [j/N]: '
        IFS= read -r answer
        case "$answer" in j|J|ja|JA|Ja) ;; *) log "Abgebrochen."; return ;; esac
    fi
    stop_services || true
    disable_autostart || true
    unset_kienzledoku_environment
    [[ "$INSTALL_ROOT" == "$HOME/Library/Application Support/Kienzledoku Local AI" ]] || \
        die "Sicherheitsprüfung des Installationspfads fehlgeschlagen."
    [[ "$LOG_DIR" == "$HOME/Library/Logs/Kienzledoku Local AI" ]] || \
        die "Sicherheitsprüfung des Logpfads fehlgeschlagen."
    rm -rf "$INSTALL_ROOT"
    rm -rf "$LOG_DIR"
    log "Entfernt wurden ausschließlich Kienzledoku Local AI, seine Modelle und LaunchAgents."
    log "Homebrew, Homebrew-Pakete und die Kienzledoku-App blieben unverändert."
}

self_test() {
    local python saved_components saved_address
    python="$(command -v python3 2>/dev/null || true)"
    [[ -n "$python" ]] || die "python3 fehlt für den Selbsttest."
    "$python" - "$SCRIPT_DIR/asr_server_mlx.py" "$SCRIPT_DIR/diarization_server_mps.py" <<'PY'
from pathlib import Path
import sys
for name in sys.argv[1:]:
    path = Path(name)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("Python-Syntaxprüfung erfolgreich.")
PY
    "$python" "$SCRIPT_DIR/asr_server_mlx.py" --self-test
    "$python" "$SCRIPT_DIR/diarization_server_mps.py" --self-test
    [[ "$QWEN_FILENAME" == "Qwen_Qwen3.5-9B-Q6_K.gguf" ]]
    [[ "$QWEN_SHA256" == "073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef" ]]
    [[ "$QWEN_SIZE" == "7958818848" ]]
    [[ "$LLAMA_REF" == "aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3" ]]
    saved_components="$SELECTED_COMPONENTS"
    saved_address="$LISTEN_ADDRESS"
    normalize_components "1,3"
    [[ "$SELECTED_COMPONENTS" == "llm,diarization" ]]
    component_selected llm
    ! component_selected asr
    component_selected diarization
    normalize_components "1,2,3,"
    [[ "$SELECTED_COMPONENTS" == "llm,asr,diarization" ]]
    valid_ipv4 "127.0.0.1"
    valid_ipv4 "0.0.0.0"
    ! valid_ipv4 "300.1.2.3"
    LISTEN_ADDRESS="0.0.0.0"
    [[ "$(connection_address)" == "127.0.0.1" ]]
    SELECTED_COMPONENTS="$saved_components"
    LISTEN_ADDRESS="$saved_address"
    log "Statischer Installer-Selbsttest erfolgreich."
}

case "$ACTION" in
    install) install_action ;;
    start) detect_native_macos; start_services ;;
    stop) detect_native_macos; stop_services ;;
    restart) detect_native_macos; stop_services; start_services ;;
    status) detect_native_macos; status_services ;;
    test) detect_native_macos; test_services ;;
    enable-autostart) detect_native_macos; enable_autostart ;;
    disable-autostart) detect_native_macos; disable_autostart ;;
    uninstall) uninstall_action ;;
    self-test) self_test ;;
    run-service) run_service ;;
    set-environment) set_kienzledoku_environment ;;
esac
