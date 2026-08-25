#!/usr/bin/env bash
# Kienzlefon AI CUDA server installer
# Version: 2.0

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

readonly INSTALLER_VERSION="2.0"
readonly PRODUCT="Kienzlefon AI CUDA Server"
readonly STATE_FILE="/etc/kienzlefon-ai/installer-v2.conf"
readonly CORE_CONFIG="/etc/kienzlefon-ai/kienzlefon-ai-v2.toml"
readonly PYANNOTE_ENV="/etc/kienzlefon-ai/diarization.env"
readonly PYANNOTE_UNIT="kienzlefon-ai-diarization.service"
readonly PYANNOTE_UNIT_FILE="/etc/systemd/system/${PYANNOTE_UNIT}"
readonly PYANNOTE_VENV="/opt/kienzlefon-ai-v2/python/diarization-venv"
readonly PYANNOTE_SERVER="/opt/kienzlefon-ai-v2/scripts/diarization_server.py"
readonly PYANNOTE_HF_HOME="/opt/kienzlefon-ai-v2/models/huggingface"
readonly QWEN_UNIT="kienzlefon-qwen3-tts.service"

ACTION="install"
NON_INTERACTIVE="n"
WITH_PYANNOTE=""
NO_START="n"
SKIP_TESTS="n"
BIND_ADDRESS="127.0.0.1"
LLM_PORT="8080"
ASR_PORT="8178"
ASR_BACKEND_PORT="8179"
ASR_BACKEND_BIND_ADDRESS="127.0.0.1"
TTS_PORT="8182"
PYANNOTE_PORT="8183"
BIND_EXPLICIT="n"
LLM_PORT_EXPLICIT="n"
ASR_PORT_EXPLICIT="n"
ASR_BACKEND_PORT_EXPLICIT="n"
ASR_BACKEND_BIND_EXPLICIT="n"
TTS_PORT_EXPLICIT="n"
PYANNOTE_PORT_EXPLICIT="n"
HF_TOKEN_FILE=""
HF_TOKEN_VALUE=""
RENDER_PAYLOADS=""
SELECTED_ROLES=()
ROLE_ALL_SELECTED="n"
GPU_ROWS=()
LLM_GPU_REQUEST=""
ASR_GPU_REQUEST=""
TTS_GPU_REQUEST=""
PYANNOTE_GPU_REQUEST=""
LLM_GPU_UUID=""
ASR_GPU_UUID=""
TTS_GPU_UUID=""
PYANNOTE_GPU_UUID=""
STATE_ENABLED_ROLES=""
STATE_LLM_GPU_UUID=""
STATE_ASR_GPU_UUID=""
STATE_TTS_GPU_UUID=""
STATE_PYANNOTE_GPU_UUID=""
STATE_BIND_ADDRESS=""
STATE_LLM_PORT=""
STATE_ASR_PORT=""
STATE_ASR_BACKEND_PORT=""
STATE_ASR_BACKEND_BIND_ADDRESS=""
STATE_TTS_PORT=""
STATE_PYANNOTE_PORT=""
TEMP_DIR=""

log() { printf '[kienzlefon-ai 2.0] %s\n' "$*"; }
warn() { printf '[kienzlefon-ai 2.0] WARNUNG: %s\n' "$*" >&2; }
die() { printf '[kienzlefon-ai 2.0] FEHLER: %s\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    case "$TEMP_DIR" in /tmp/kienzlefon-ai-v2.*) rm -rf -- "$TEMP_DIR" ;; esac
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Kienzlefon AI CUDA Server Installer v2.0

Dieser Installer verwaltet nur die residenten KI-Rollen auf Ubuntu/NVIDIA:

  llm       Sprachmodell: versteht den Dialog und erzeugt strukturierte Antworten.
            Qwen3.5-9B Q6_K über llama.cpp, Port 8080.
  asr       Automatic Speech Recognition: wandelt Sprache in Text um.
            Genau ein WhisperLiveKit/Whisper-large-v3-Dienst, Ports 8178/8179.
  tts       Text to Speech: wandelt Antworttext in Sprache um.
            Qwen3-TTS 0.6B CustomVoice, CUDA/INT8, Port 8182, Stimme uncle_fu.
            Piper auf Port 8181 bleibt der vorhandene, nicht verwaltete Fallback.
  pyannote  Optionale Sprechertrennung für die Gesprächsdokumentation.
            Eigenständiger Community-1-Dienst, Port 8183; nicht Teil der ASR.
  all       llm + asr + tts; pyannote wird immer zusätzlich ausdrücklich abgefragt.

Aufruf:
  ./install_kienzlefon_ai_server.sh --role all
  ./install_kienzlefon_ai_server.sh --role llm --llm-gpu 0
  ./install_kienzlefon_ai_server.sh --action status

Aktionen:
  --action install|configure|start|stop|restart|status|test|uninstall
  --role llm|asr|tts|pyannote|all   Mehrfach möglich

GPU-Auswahl (Index oder stabile NVIDIA-UUID):
  --llm-gpu WERT
  --asr-gpu WERT
  --tts-gpu WERT
  --pyannote-gpu WERT

Pyannote:
  --with-pyannote             Bei --role all ohne Rückfrage einschließen
  --without-pyannote          Bei --role all ausdrücklich nicht einschließen
  --hf-token-file DATEI       Verdeckte Tokenübergabe über eine geschützte Datei

Weitere Optionen:
  --bind ADRESSE              Standard: 127.0.0.1
  --llm-port PORT             Standard: 8080
  --asr-port PORT             Standard: 8178
  --asr-backend-port PORT     Standard: 8179
  --asr-backend-bind ADRESSE  127.0.0.1 oder 0.0.0.0; für einen entfernten
                              Kienzledoku-Client ist 0.0.0.0 plus Firewall nötig
  --tts-port PORT             Standard: 8182
  --pyannote-port PORT        Standard: 8183
  --non-interactive           Keine Rückfragen
  --no-start                  Dienste nach Installation nicht resident lassen
  --skip-tests                Zeitintensive Laufzeittests überspringen
  --self-test                 Isolierter statischer Installer-Selbsttest
  --version
  --help

Voraussetzungen:
  Ubuntu x86_64, systemd, funktionsfähiger NVIDIA-Treiber und vorhandenes CUDA/nvcc.
  Kein stiller CPU-Fallback für LLM, ASR, Qwen-TTS oder Pyannote.
  NVIDIA-Treiber und CUDA werden geprüft, aber nicht installiert oder verändert.

Wichtig: Nicht mit sudo starten. Als normaler Benutzer mit sudo-Berechtigung ausführen.
EOF
}

role_known() {
  case "$1" in llm|asr|tts|pyannote) return 0 ;; *) return 1 ;; esac
}

contains_role() {
  local wanted="$1" item
  shift
  for item in "$@"; do [[ "$item" == "$wanted" ]] && return 0; done
  return 1
}

add_role() {
  local role="$1"
  [[ "$role" != "all" ]] || {
    add_role llm; add_role asr; add_role tts
    return
  }
  role_known "$role" || die "Unbekannte Rolle: $role"
  contains_role "$role" "${SELECTED_ROLES[@]:-}" || SELECTED_ROLES+=("$role")
}

require_port() {
  local label="$1" value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] && ((value >= 1 && value <= 65535)) \
    || die "$label muss zwischen 1 und 65535 liegen."
}

validate_network_values() {
  [[ "$BIND_ADDRESS" =~ ^[A-Za-z0-9._:-]+$ ]] || die "Bind-Adresse enthält unzulässige Zeichen."
  case "$ASR_BACKEND_BIND_ADDRESS" in
    127.0.0.1|0.0.0.0) ;;
    *) die "ASR-Backend-Bind erlaubt nur 127.0.0.1 oder 0.0.0.0." ;;
  esac
  require_port "LLM-Port" "$LLM_PORT"
  require_port "ASR-Port" "$ASR_PORT"
  require_port "ASR-Backend-Port" "$ASR_BACKEND_PORT"
  require_port "TTS-Port" "$TTS_PORT"
  require_port "Pyannote-Port" "$PYANNOTE_PORT"
  [[ "$LLM_PORT" != "$ASR_PORT" && "$LLM_PORT" != "$ASR_BACKEND_PORT" && "$LLM_PORT" != "$TTS_PORT" && "$LLM_PORT" != "$PYANNOTE_PORT" ]] || die "Portkollision erkannt."
  [[ "$ASR_PORT" != "$ASR_BACKEND_PORT" && "$ASR_PORT" != "$TTS_PORT" && "$ASR_PORT" != "$PYANNOTE_PORT" ]] || die "Portkollision erkannt."
  [[ "$ASR_BACKEND_PORT" != "$TTS_PORT" && "$ASR_BACKEND_PORT" != "$PYANNOTE_PORT" && "$TTS_PORT" != "$PYANNOTE_PORT" ]] || die "Portkollision erkannt."
}

parse_args() {
  local saw_all="n"
  while (($#)); do
    case "$1" in
      --action) [[ $# -ge 2 ]] || die "Wert für --action fehlt."; ACTION="$2"; shift 2 ;;
      --role)
        [[ $# -ge 2 ]] || die "Wert für --role fehlt."
        if [[ "$2" == "all" ]]; then saw_all="y"; ROLE_ALL_SELECTED="y"; fi
        add_role "$2"; shift 2
        ;;
      --llm-gpu) [[ $# -ge 2 ]] || die "Wert für --llm-gpu fehlt."; LLM_GPU_REQUEST="$2"; shift 2 ;;
      --asr-gpu) [[ $# -ge 2 ]] || die "Wert für --asr-gpu fehlt."; ASR_GPU_REQUEST="$2"; shift 2 ;;
      --tts-gpu) [[ $# -ge 2 ]] || die "Wert für --tts-gpu fehlt."; TTS_GPU_REQUEST="$2"; shift 2 ;;
      --pyannote-gpu) [[ $# -ge 2 ]] || die "Wert für --pyannote-gpu fehlt."; PYANNOTE_GPU_REQUEST="$2"; shift 2 ;;
      --with-pyannote) WITH_PYANNOTE="y"; shift ;;
      --without-pyannote) WITH_PYANNOTE="n"; shift ;;
      --hf-token-file) [[ $# -ge 2 ]] || die "Wert für --hf-token-file fehlt."; HF_TOKEN_FILE="$2"; shift 2 ;;
      --bind) [[ $# -ge 2 ]] || die "Wert für --bind fehlt."; BIND_ADDRESS="$2"; BIND_EXPLICIT="y"; shift 2 ;;
      --llm-port) [[ $# -ge 2 ]] || die "Wert für --llm-port fehlt."; LLM_PORT="$2"; LLM_PORT_EXPLICIT="y"; shift 2 ;;
      --asr-port) [[ $# -ge 2 ]] || die "Wert für --asr-port fehlt."; ASR_PORT="$2"; ASR_PORT_EXPLICIT="y"; shift 2 ;;
      --asr-backend-port) [[ $# -ge 2 ]] || die "Wert für --asr-backend-port fehlt."; ASR_BACKEND_PORT="$2"; ASR_BACKEND_PORT_EXPLICIT="y"; shift 2 ;;
      --asr-backend-bind) [[ $# -ge 2 ]] || die "Wert für --asr-backend-bind fehlt."; ASR_BACKEND_BIND_ADDRESS="$2"; ASR_BACKEND_BIND_EXPLICIT="y"; shift 2 ;;
      --tts-port) [[ $# -ge 2 ]] || die "Wert für --tts-port fehlt."; TTS_PORT="$2"; TTS_PORT_EXPLICIT="y"; shift 2 ;;
      --pyannote-port) [[ $# -ge 2 ]] || die "Wert für --pyannote-port fehlt."; PYANNOTE_PORT="$2"; PYANNOTE_PORT_EXPLICIT="y"; shift 2 ;;
      --non-interactive) NON_INTERACTIVE="y"; shift ;;
      --no-start) NO_START="y"; shift ;;
      --skip-tests) SKIP_TESTS="y"; shift ;;
      --self-test) ACTION="self-test"; shift ;;
      --render-payloads) [[ $# -ge 2 ]] || die "Ziel für --render-payloads fehlt."; RENDER_PAYLOADS="$2"; ACTION="render-payloads"; shift 2 ;;
      --version) printf '%s\n' "$INSTALLER_VERSION"; exit 0 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unbekannte Option: $1" ;;
    esac
  done
  case "$ACTION" in install|configure|start|stop|restart|status|test|uninstall|self-test|render-payloads) ;; *) die "Ungültige Aktion: $ACTION" ;; esac
  [[ "$WITH_PYANNOTE" != "y" || "$saw_all" == "y" ]] \
    || die "--with-pyannote ist nur zusammen mit --role all sinnvoll; sonst --role pyannote verwenden."
  validate_network_values
  if [[ "$ASR_BACKEND_BIND_ADDRESS" == "0.0.0.0" ]]; then
    warn "Port $ASR_BACKEND_PORT wird auf allen Server-Schnittstellen geöffnet; Zugriff per Firewall auf den Kienzledoku-Client begrenzen."
  fi
}

load_state() {
  local state_path="${1:-$STATE_FILE}" key value
  [[ -r "$state_path" ]] || return 0
  while IFS='=' read -r key value; do
    case "$key" in
      enabled_roles) STATE_ENABLED_ROLES="$value" ;;
      llm_gpu_uuid) STATE_LLM_GPU_UUID="$value" ;;
      asr_gpu_uuid) STATE_ASR_GPU_UUID="$value" ;;
      tts_gpu_uuid) STATE_TTS_GPU_UUID="$value" ;;
      pyannote_gpu_uuid) STATE_PYANNOTE_GPU_UUID="$value" ;;
      bind_address) STATE_BIND_ADDRESS="$value" ;;
      llm_port) STATE_LLM_PORT="$value" ;;
      asr_port) STATE_ASR_PORT="$value" ;;
      asr_backend_port) STATE_ASR_BACKEND_PORT="$value" ;;
      asr_backend_bind_address) STATE_ASR_BACKEND_BIND_ADDRESS="$value" ;;
      tts_port) STATE_TTS_PORT="$value" ;;
      pyannote_port) STATE_PYANNOTE_PORT="$value" ;;
    esac
  done < "$state_path"
  [[ "$BIND_EXPLICIT" == "y" || -z "$STATE_BIND_ADDRESS" ]] || BIND_ADDRESS="$STATE_BIND_ADDRESS"
  [[ "$LLM_PORT_EXPLICIT" == "y" || -z "$STATE_LLM_PORT" ]] || LLM_PORT="$STATE_LLM_PORT"
  [[ "$ASR_PORT_EXPLICIT" == "y" || -z "$STATE_ASR_PORT" ]] || ASR_PORT="$STATE_ASR_PORT"
  [[ "$ASR_BACKEND_PORT_EXPLICIT" == "y" || -z "$STATE_ASR_BACKEND_PORT" ]] || ASR_BACKEND_PORT="$STATE_ASR_BACKEND_PORT"
  [[ "$ASR_BACKEND_BIND_EXPLICIT" == "y" || -z "$STATE_ASR_BACKEND_BIND_ADDRESS" ]] || ASR_BACKEND_BIND_ADDRESS="$STATE_ASR_BACKEND_BIND_ADDRESS"
  [[ "$TTS_PORT_EXPLICIT" == "y" || -z "$STATE_TTS_PORT" ]] || TTS_PORT="$STATE_TTS_PORT"
  [[ "$PYANNOTE_PORT_EXPLICIT" == "y" || -z "$STATE_PYANNOTE_PORT" ]] || PYANNOTE_PORT="$STATE_PYANNOTE_PORT"
  validate_network_values
}

roles_csv() { local IFS=,; printf '%s' "$*"; }

save_state() {
  local tmp enabled item old_ifs="$IFS"
  local -a stored=() final=()
  IFS=','
  for item in $STATE_ENABLED_ROLES; do [[ -n "$item" ]] && stored+=("$item"); done
  IFS="$old_ifs"
  if [[ "$ACTION" == "uninstall" ]]; then
    for item in "${stored[@]:-}"; do contains_role "$item" "${SELECTED_ROLES[@]}" || final+=("$item"); done
  else
    for item in llm asr tts pyannote; do
      if contains_role "$item" "${stored[@]:-}" || contains_role "$item" "${SELECTED_ROLES[@]:-}"; then final+=("$item"); fi
    done
  fi
  enabled="$(roles_csv "${final[@]:-}")"
  tmp="$(mktemp)"
  {
    printf 'installer_version=2.0\n'
    printf 'enabled_roles=%s\n' "$enabled"
    printf 'llm_gpu_uuid=%s\n' "$LLM_GPU_UUID"
    printf 'asr_gpu_uuid=%s\n' "$ASR_GPU_UUID"
    printf 'tts_gpu_uuid=%s\n' "$TTS_GPU_UUID"
    printf 'pyannote_gpu_uuid=%s\n' "$PYANNOTE_GPU_UUID"
    printf 'bind_address=%s\n' "$BIND_ADDRESS"
    printf 'llm_port=%s\n' "$LLM_PORT"
    printf 'asr_port=%s\n' "$ASR_PORT"
    printf 'asr_backend_port=%s\n' "$ASR_BACKEND_PORT"
    printf 'asr_backend_bind_address=%s\n' "$ASR_BACKEND_BIND_ADDRESS"
    printf 'tts_port=%s\n' "$TTS_PORT"
    printf 'pyannote_port=%s\n' "$PYANNOTE_PORT"
  } > "$tmp"
  sudo install -d -m 0755 /etc/kienzlefon-ai
  sudo install -m 0644 -o root -g root "$tmp" "$STATE_FILE"
  rm -f -- "$tmp"
}

select_roles_interactive() {
  local answer=""
  printf '\nWelche KI-Rollen sollen bearbeitet werden?\n'
  printf '  1 = llm\n  2 = asr\n  3 = tts\n  4 = pyannote\n  all = llm + asr + tts\n'
  read -r -p 'Auswahl (z. B. 1,2 oder all): ' answer
  answer="${answer// /}"
  case "$answer" in
    all) ROLE_ALL_SELECTED="y"; add_role all ;;
    *)
      local item
      local old_ifs="$IFS"; IFS=','
      for item in $answer; do
        case "$item" in 1|llm) add_role llm ;; 2|asr) add_role asr ;; 3|tts) add_role tts ;; 4|pyannote) add_role pyannote ;; *) die "Ungültige Rollenauswahl: $item" ;; esac
      done
      IFS="$old_ifs"
      ;;
  esac
}

resolve_roles() {
  local answer=""
  if ((${#SELECTED_ROLES[@]} == 0)); then
    if [[ "$ACTION" == "install" ]]; then
      [[ "$NON_INTERACTIVE" == "n" ]] || die "Im nichtinteraktiven Modus mindestens eine --role angeben."
      select_roles_interactive
    else
      local item old_ifs="$IFS"; IFS=','
      for item in $STATE_ENABLED_ROLES; do [[ -n "$item" ]] && add_role "$item"; done
      IFS="$old_ifs"
    fi
  fi
  ((${#SELECTED_ROLES[@]})) || die "Keine Rollen ausgewählt oder im Zustand gespeichert."
  if [[ "$ROLE_ALL_SELECTED" == "y" ]] && ! contains_role pyannote "${SELECTED_ROLES[@]}"; then
    if [[ "$WITH_PYANNOTE" == "y" ]]; then
      add_role pyannote
    elif [[ "$WITH_PYANNOTE" == "" ]]; then
      if [[ "$NON_INTERACTIVE" == "y" ]]; then
        die "Bei --role all im nichtinteraktiven Modus --with-pyannote oder --without-pyannote angeben."
      fi
      printf '\nPyannote trennt Sprecher für die spätere Dokumentation. Es ist kein Teil der Kern-ASR.\n'
      read -r -p 'Optionalen GPU-Pyannote-Dienst installieren? [j/N]: ' answer
      case "$answer" in j|J|ja|Ja|JA|y|Y|yes|YES) add_role pyannote ;; esac
    fi
  fi
}

require_cuda_platform() {
  [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || die "Version 2.0 unterstützt nur Ubuntu x86_64 mit NVIDIA/CUDA."
  [[ -r /etc/os-release ]] || die "/etc/os-release fehlt."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "Version 2.0 unterstützt nur Ubuntu; erkannt: ${ID:-unbekannt}."
  [[ "$EUID" -ne 0 ]] || die "Bitte als normaler sudo-Benutzer starten, nicht direkt als root."
  command -v sudo >/dev/null || die "sudo fehlt."
  command -v systemctl >/dev/null || die "systemd fehlt."
  command -v nvidia-smi >/dev/null || die "nvidia-smi fehlt; kein CPU-Fallback."
  nvidia-smi >/dev/null 2>&1 || die "NVIDIA-Treiber ist nicht funktionsfähig; kein CPU-Fallback."
  command -v nvcc >/dev/null || die "CUDA Toolkit/nvcc fehlt. CUDA wird vom Installer nicht verändert."
  sudo -v
}

load_gpus() {
  mapfile -t GPU_ROWS < <(nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv,noheader,nounits)
  ((${#GPU_ROWS[@]})) || die "nvidia-smi meldet keine GPU."
}

gpu_uuid_for_value() {
  local wanted="$1" row index uuid name memory
  for row in "${GPU_ROWS[@]}"; do
    IFS=',' read -r index uuid name memory <<< "$row"
    index="${index//[[:space:]]/}"; uuid="${uuid//[[:space:]]/}"
    if [[ "$wanted" == "$index" || "$wanted" == "$uuid" ]]; then printf '%s\n' "$uuid"; return 0; fi
  done
  return 1
}

select_gpu_for_role() {
  local role="$1" requested="$2" saved="$3" selected="" row index uuid name memory default=""
  if [[ -n "$requested" ]]; then
    selected="$(gpu_uuid_for_value "$requested")" || die "GPU-Auswahl für $role ist ungültig: $requested"
  elif [[ "$NON_INTERACTIVE" == "y" ]]; then
    if [[ -n "$saved" ]] && selected="$(gpu_uuid_for_value "$saved")"; then :
    elif ((${#GPU_ROWS[@]} == 1)); then selected="$(gpu_uuid_for_value 0)"
    else die "Mehrere GPUs vorhanden: --${role}-gpu mit Index oder UUID angeben."
    fi
  else
    printf '\nGPU-Auswahl für Rolle %s:\n' "$role"
    for row in "${GPU_ROWS[@]}"; do
      IFS=',' read -r index uuid name memory <<< "$row"
      printf '  Index %s | %s | %s | %s MiB\n' "${index// /}" "${uuid// /}" "${name# }" "${memory// /}"
    done
    [[ -n "$saved" ]] && default="$saved" || default="0"
    read -r -p "Index oder UUID [${default}]: " requested
    requested="${requested:-$default}"
    selected="$(gpu_uuid_for_value "$requested")" || die "GPU-Auswahl für $role ist ungültig: $requested"
  fi
  printf -v "${role^^}_GPU_UUID" '%s' "$selected"
  log "Rolle $role verwendet dauerhaft GPU UUID $selected."
}

resolve_gpus() {
  local role
  load_gpus
  for role in "${SELECTED_ROLES[@]}"; do
    case "$role" in
      llm) select_gpu_for_role llm "$LLM_GPU_REQUEST" "$STATE_LLM_GPU_UUID" ;;
      asr) select_gpu_for_role asr "$ASR_GPU_REQUEST" "$STATE_ASR_GPU_UUID" ;;
      tts) select_gpu_for_role tts "$TTS_GPU_REQUEST" "$STATE_TTS_GPU_UUID" ;;
      pyannote) select_gpu_for_role pyannote "$PYANNOTE_GPU_REQUEST" "$STATE_PYANNOTE_GPU_UUID" ;;
    esac
  done
  LLM_GPU_UUID="${LLM_GPU_UUID:-$STATE_LLM_GPU_UUID}"
  ASR_GPU_UUID="${ASR_GPU_UUID:-$STATE_ASR_GPU_UUID}"
  TTS_GPU_UUID="${TTS_GPU_UUID:-$STATE_TTS_GPU_UUID}"
  PYANNOTE_GPU_UUID="${PYANNOTE_GPU_UUID:-$STATE_PYANNOTE_GPU_UUID}"
}

gpu_dropin_unit() {
  case "$1" in
    llm) printf 'kienzlefon-ai-llm.service\n' ;;
    asr) printf 'kienzlefon-ai-asr-backend.service\n' ;;
    tts) printf '%s\n' "$QWEN_UNIT" ;;
    pyannote) printf '%s\n' "$PYANNOTE_UNIT" ;;
  esac
}

persist_gpu_dropin() {
  local role="$1" uuid="$2" unit dir tmp
  [[ -n "$uuid" ]] || die "Keine GPU-UUID für $role aufgelöst."
  unit="$(gpu_dropin_unit "$role")"
  dir="/etc/systemd/system/${unit}.d"
  tmp="$(mktemp)"
  printf '[Service]\nEnvironment=CUDA_VISIBLE_DEVICES=%s\n' "$uuid" > "$tmp"
  sudo install -d -m 0755 "$dir"
  sudo install -m 0644 -o root -g root "$tmp" "$dir/10-kienzlefon-gpu.conf"
  rm -f -- "$tmp"
}

prepare_payloads() {
  TEMP_DIR="$(mktemp -d /tmp/kienzlefon-ai-v2.XXXXXX)"
  write_core_payload > "$TEMP_DIR/core.sh"
  write_qwen_payload > "$TEMP_DIR/qwen.sh"
  write_diarization_server > "$TEMP_DIR/diarization_server.py"
  chmod 0755 "$TEMP_DIR/core.sh" "$TEMP_DIR/qwen.sh"
  chmod 0644 "$TEMP_DIR/diarization_server.py"
}

core_args() {
  local action="$1" role arg
  printf '%s\0' --action "$action" --role "$role"
  case "$role" in
    llm) printf '%s\0' --llm-port "$LLM_PORT" --llm-slots 3 --llm-context 131072 --llm-kv-cache q8_0 ;;
    asr)
      printf '%s\0' --asr-port "$ASR_PORT" --asr-backend-port "$ASR_BACKEND_PORT" --asr-frame-threshold 25
      printf '%s\0' --asr-backend-bind "$ASR_BACKEND_BIND_ADDRESS"
      if [[ "$ASR_BACKEND_BIND_ADDRESS" == "0.0.0.0" ]]; then
        printf '%s\0' --confirm-asr-backend-network-exposure
      fi
      ;;
  esac
  if [[ "$BIND_ADDRESS" != "127.0.0.1" ]]; then printf '%s\0' --bind "$BIND_ADDRESS" --confirm-nonloopback-bind; fi
  [[ "$NO_START" == "n" ]] || printf '%s\0' --no-start
  [[ "$SKIP_TESTS" == "n" ]] || printf '%s\0' --skip-tests
}

run_core() {
  local action="$1" role="$2"
  local -a args=()
  mapfile -d '' -t args < <(core_args "$action" "$role")
  bash "$TEMP_DIR/core.sh" "${args[@]}"
}

install_qwen() {
  persist_gpu_dropin tts "$TTS_GPU_UUID"
  # Frühere, ausdrücklich Qwen-eigene Laufzeit-Drop-ins dürfen den neuen
  # einheitlichen INT8-/Batch-1-Stand nicht übersteuern. Der GPU-Drop-in dieses
  # Installers und sämtliche Piper-Dateien bleiben unberührt.
  sudo rm -f -- \
    "/etc/systemd/system/${QWEN_UNIT}.d/override.conf" \
    "/etc/systemd/system/${QWEN_UNIT}.d/20-batch-size.conf" \
    "/etc/systemd/system/${QWEN_UNIT}.d/99-runtime-tuning.conf"
  sudo env KIENZLEFON_SELECTED_GPU_UUID="$TTS_GPU_UUID" bash "$TEMP_DIR/qwen.sh" \
    --port "$TTS_PORT" --threads 4 --batch-size 1 --skip-benchmark
  if [[ "$NO_START" == "y" ]]; then sudo systemctl stop "$QWEN_UNIT"; fi
  check_piper_fallback
}

check_piper_fallback() {
  if curl -fsS --max-time 3 http://127.0.0.1:8181/health >/dev/null 2>&1; then
    log "Vorhandener Piper-Fallback auf Port 8181 ist erreichbar."
  else
    warn "Piper-Fallback auf Port 8181 ist nicht erreichbar. Dieser Installer installiert, verändert oder entfernt Piper nicht."
  fi
}

token_instructions() {
  cat <<'EOF'

Pyannote benötigt für den ersten Modelldownload einen Hugging-Face-Token:
  1. Auf https://huggingface.co registrieren/anmelden.
  2. Die Modellseite pyannote/speaker-diarization-community-1 öffnen und die
     Nutzungsbedingungen akzeptieren.
  3. Unter Settings -> Access Tokens einen persönlichen Read-Token erzeugen.
  4. Den Token verdeckt eingeben oder in einer Datei mit chmod 600 ablegen und
     deren Pfad mit --hf-token-file übergeben.

Der Token wird nicht als Klartext-CLI-Argument, nicht in der allgemeinen TOML
und nicht in normalen Logs gespeichert. Er liegt ausschließlich root-lesbar in
/etc/kienzlefon-ai/diarization.env (Modus 0600).
EOF
}

read_hf_token() {
  local token=""
  token_instructions
  if [[ -n "$HF_TOKEN_FILE" ]]; then
    [[ -r "$HF_TOKEN_FILE" ]] || die "Token-Datei ist nicht lesbar: $HF_TOKEN_FILE"
    IFS= read -r token < "$HF_TOKEN_FILE"
  elif sudo test -r "$PYANNOTE_ENV" 2>/dev/null; then
    token="$(sudo awk -F= '$1=="HF_TOKEN" {sub(/^[^=]*=/, ""); print; exit}' "$PYANNOTE_ENV")"
    [[ -n "$token" ]] && log "Vorhandener geschützter Pyannote-Token wird weiterverwendet."
  elif [[ "$NON_INTERACTIVE" == "n" ]]; then
    read -r -s -p 'HF_TOKEN (Eingabe bleibt verborgen): ' token
    printf '\n'
  else
    die "Pyannote benötigt --hf-token-file oder einen vorhandenen geschützten Token."
  fi
  [[ "$token" =~ ^hf_[A-Za-z0-9]{20,}$ ]] || die "Der Hugging-Face-Token besitzt kein plausibles Format."
  HF_TOKEN_VALUE="$token"
}

install_pyannote() {
  local token user group python tmp unit_tmp
  read_hf_token
  token="$HF_TOKEN_VALUE"
  user="$(id -un)"; group="$(id -gn)"
  python="$(command -v python3.12 || command -v python3.11 || command -v python3)"
  [[ -n "$python" ]] || die "Python 3.11 oder 3.12 fehlt."
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip ffmpeg curl
  sudo install -d -m 0755 -o "$user" -g "$group" \
    /opt/kienzlefon-ai-v2/python /opt/kienzlefon-ai-v2/scripts /opt/kienzlefon-ai-v2/models "$PYANNOTE_HF_HOME"
  sudo install -m 0644 -o "$user" -g "$group" "$TEMP_DIR/diarization_server.py" "$PYANNOTE_SERVER"
  [[ -x "$PYANNOTE_VENV/bin/python" ]] || "$python" -m venv "$PYANNOTE_VENV"
  "$PYANNOTE_VENV/bin/python" -m pip install --upgrade pip
  "$PYANNOTE_VENV/bin/pip" install --upgrade --index-url https://download.pytorch.org/whl/cu130 'torch==2.11.0' 'torchaudio==2.11.0'
  "$PYANNOTE_VENV/bin/pip" install --upgrade 'pyannote.audio>=4.0,<5'
  CUDA_VISIBLE_DEVICES="$PYANNOTE_GPU_UUID" "$PYANNOTE_VENV/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise SystemExit("Pyannote sieht die ausgewählte CUDA-GPU nicht; kein CPU-Fallback.")
print("Pyannote CUDA:", torch.cuda.get_device_name(0), "| Torch CUDA:", torch.version.cuda)
PY
  tmp="$(mktemp)"
  {
    printf 'HF_TOKEN=%s\n' "$token"
    printf 'HF_HOME=%s\n' "$PYANNOTE_HF_HOME"
    printf 'PYANNOTE_MODEL=pyannote/speaker-diarization-community-1\n'
    printf 'DIARIZATION_DEVICE=cuda:0\n'
    printf 'DIARIZATION_HOST=%s\n' "$BIND_ADDRESS"
    printf 'DIARIZATION_PORT=%s\n' "$PYANNOTE_PORT"
  } > "$tmp"
  sudo install -d -m 0755 /etc/kienzlefon-ai
  sudo install -m 0600 -o root -g root "$tmp" "$PYANNOTE_ENV"
  rm -f -- "$tmp"
  unit_tmp="$(mktemp)"
  cat > "$unit_tmp" <<EOF
[Unit]
Description=Kienzlefon AI optional pyannote diarization
After=network.target

[Service]
Type=simple
User=${user}
Group=${group}
WorkingDirectory=/opt/kienzlefon-ai-v2
EnvironmentFile=${PYANNOTE_ENV}
Environment=PYTHONUNBUFFERED=1
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ExecStart=${PYANNOTE_VENV}/bin/python ${PYANNOTE_SERVER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 0644 -o root -g root "$unit_tmp" "$PYANNOTE_UNIT_FILE"
  rm -f -- "$unit_tmp"
  persist_gpu_dropin pyannote "$PYANNOTE_GPU_UUID"
  sudo systemctl daemon-reload
  sudo systemctl enable "$PYANNOTE_UNIT"
  if [[ "$NO_START" == "n" ]]; then
    sudo systemctl restart "$PYANNOTE_UNIT"
    if [[ "$SKIP_TESTS" == "n" ]]; then wait_http "http://127.0.0.1:${PYANNOTE_PORT}/health" 600; fi
  fi
  token=""
  HF_TOKEN_VALUE=""
}

wait_http() {
  local url="$1" seconds="$2" i
  for ((i=0; i<seconds; i++)); do curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return 0; sleep 1; done
  die "Dienst wurde nicht rechtzeitig erreichbar: $url"
}

service_action() {
  local action="$1" role="$2" unit=""
  case "$role" in
    llm|asr) run_core "$action" "$role"; return ;;
    tts) unit="$QWEN_UNIT" ;;
    pyannote) unit="$PYANNOTE_UNIT" ;;
  esac
  case "$action" in
    start) sudo systemctl start "$unit" ;;
    stop) sudo systemctl stop "$unit" ;;
    restart|configure) sudo systemctl daemon-reload; sudo systemctl restart "$unit" ;;
    status) systemctl --no-pager --full status "$unit" ;;
    test)
      case "$role" in
        tts) curl -fsS "http://127.0.0.1:${TTS_PORT}/v1/health" >/dev/null ;;
        pyannote) curl -fsS "http://127.0.0.1:${PYANNOTE_PORT}/health" >/dev/null ;;
      esac
      ;;
  esac
}

configure_qwen() {
  local env_file="/etc/kienzlefon/qwen3-tts.env"
  local unit_file="/etc/systemd/system/${QWEN_UNIT}"
  local dropin_dir="/etc/systemd/system/${QWEN_UNIT}.d"
  local env_tmp runtime_tmp
  sudo test -f "$env_file" || die "Qwen-Konfiguration fehlt: $env_file"
  sudo test -f "$unit_file" || die "Qwen-systemd-Dienst fehlt: $unit_file"
  sudo test -x /opt/kienzlefon/qwen3-tts/bin/qwen_tts || die "Qwen-CUDA-Binary fehlt."
  sudo test -d /opt/kienzlefon/models/qwen3-tts-0.6b-customvoice || die "Qwen-Modell fehlt."
  env_tmp="$(mktemp)"
  sudo awk -v port="$TTS_PORT" '
    BEGIN { p=0; t=0; b=0; d=0; q=0 }
    /^KIENZLEFON_QWEN_PORT=/ { print "KIENZLEFON_QWEN_PORT=" port; p=1; next }
    /^KIENZLEFON_QWEN_THREADS=/ { print "KIENZLEFON_QWEN_THREADS=4"; t=1; next }
    /^KIENZLEFON_QWEN_BATCH_SIZE=/ { print "KIENZLEFON_QWEN_BATCH_SIZE=1"; b=1; next }
    /^KIENZLEFON_QWEN_DEFAULT_BACKEND=/ { print "KIENZLEFON_QWEN_DEFAULT_BACKEND=cuda"; d=1; next }
    /^KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=/ { print "KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int8"; q=1; next }
    { print }
    END {
      if (!p) print "KIENZLEFON_QWEN_PORT=" port
      if (!t) print "KIENZLEFON_QWEN_THREADS=4"
      if (!b) print "KIENZLEFON_QWEN_BATCH_SIZE=1"
      if (!d) print "KIENZLEFON_QWEN_DEFAULT_BACKEND=cuda"
      if (!q) print "KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int8"
    }
  ' "$env_file" > "$env_tmp"
  sudo install -m 0644 -o root -g root "$env_tmp" "$env_file"
  rm -f -- "$env_tmp"
  runtime_tmp="$(mktemp)"
  cat > "$runtime_tmp" <<EOF
[Service]
Environment=QWEN_CUDA_FUSED_TALKER=1
Environment=QWEN_CUDA_CONVDEC=1
UnsetEnvironment=QWEN_CUDA_BATCH
ExecStart=
ExecStart=/opt/kienzlefon/qwen3-tts/bin/qwen_tts -d /opt/kienzlefon/models/qwen3-tts-0.6b-customvoice --int8 -j 4 --backend cuda --serve ${TTS_PORT} --batch-size 1
EOF
  sudo install -d -m 0755 "$dropin_dir"
  sudo install -m 0644 -o root -g root "$runtime_tmp" "$dropin_dir/20-kienzlefon-v2-runtime.conf"
  rm -f -- "$runtime_tmp"
  sudo rm -f -- \
    "$dropin_dir/override.conf" \
    "$dropin_dir/20-batch-size.conf" \
    "$dropin_dir/99-runtime-tuning.conf"
  persist_gpu_dropin tts "$TTS_GPU_UUID"
  sudo systemctl daemon-reload
  if [[ "$NO_START" == "y" ]]; then
    sudo systemctl stop "$QWEN_UNIT"
  else
    sudo systemctl restart "$QWEN_UNIT"
    [[ "$SKIP_TESTS" == "y" ]] || wait_http "http://127.0.0.1:${TTS_PORT}/v1/health" 300
  fi
  check_piper_fallback
}

configure_pyannote() {
  local env_tmp
  sudo test -f "$PYANNOTE_ENV" || die "Pyannote-Konfiguration fehlt: $PYANNOTE_ENV"
  sudo test -f "$PYANNOTE_UNIT_FILE" || die "Pyannote-systemd-Dienst fehlt: $PYANNOTE_UNIT_FILE"
  sudo test -x "$PYANNOTE_VENV/bin/python" || die "Pyannote-Venv fehlt."
  sudo test -f "$PYANNOTE_SERVER" || die "Pyannote-Server fehlt."
  env_tmp="$(sudo mktemp /etc/kienzlefon-ai/.diarization.env.XXXXXX)"
  sudo awk -v host="$BIND_ADDRESS" -v port="$PYANNOTE_PORT" '
    BEGIN { h=0; p=0; d=0; m=0 }
    /^DIARIZATION_HOST=/ { print "DIARIZATION_HOST=" host; h=1; next }
    /^DIARIZATION_PORT=/ { print "DIARIZATION_PORT=" port; p=1; next }
    /^DIARIZATION_DEVICE=/ { print "DIARIZATION_DEVICE=cuda:0"; d=1; next }
    /^PYANNOTE_MODEL=/ { print "PYANNOTE_MODEL=pyannote/speaker-diarization-community-1"; m=1; next }
    { print }
    END {
      if (!h) print "DIARIZATION_HOST=" host
      if (!p) print "DIARIZATION_PORT=" port
      if (!d) print "DIARIZATION_DEVICE=cuda:0"
      if (!m) print "PYANNOTE_MODEL=pyannote/speaker-diarization-community-1"
    }
  ' "$PYANNOTE_ENV" | sudo tee "$env_tmp" >/dev/null
  sudo install -m 0600 -o root -g root "$env_tmp" "$PYANNOTE_ENV"
  sudo rm -f -- "$env_tmp"
  persist_gpu_dropin pyannote "$PYANNOTE_GPU_UUID"
  sudo systemctl daemon-reload
  if [[ "$NO_START" == "y" ]]; then
    sudo systemctl stop "$PYANNOTE_UNIT"
  else
    sudo systemctl restart "$PYANNOTE_UNIT"
    [[ "$SKIP_TESTS" == "y" ]] || wait_http "http://127.0.0.1:${PYANNOTE_PORT}/health" 600
  fi
}

uninstall_pyannote() {
  sudo systemctl disable --now "$PYANNOTE_UNIT" >/dev/null 2>&1 || true
  sudo rm -f -- "$PYANNOTE_UNIT_FILE"
  sudo rm -rf -- "$PYANNOTE_VENV" "$PYANNOTE_HF_HOME"
  sudo rm -f -- "$PYANNOTE_SERVER" "$PYANNOTE_ENV"
  sudo rm -rf -- "/etc/systemd/system/${PYANNOTE_UNIT}.d"
  sudo systemctl daemon-reload
}

uninstall_role() {
  case "$1" in
    llm)
      run_core uninstall llm
      sudo rm -rf -- /etc/systemd/system/kienzlefon-ai-llm.service.d
      ;;
    asr)
      run_core uninstall asr
      sudo rm -rf -- /etc/systemd/system/kienzlefon-ai-asr-backend.service.d
      ;;
    tts)
      sudo bash "$TEMP_DIR/qwen.sh" --uninstall
      sudo rm -rf -- "/etc/systemd/system/${QWEN_UNIT}.d"
      sudo systemctl daemon-reload
      ;;
    pyannote) uninstall_pyannote ;;
  esac
}

install_selected() {
  local role
  for role in "${SELECTED_ROLES[@]}"; do
    case "$role" in
      llm) persist_gpu_dropin llm "$LLM_GPU_UUID"; run_core install llm ;;
      asr) persist_gpu_dropin asr "$ASR_GPU_UUID"; run_core install asr ;;
      tts) install_qwen ;;
      pyannote) install_pyannote ;;
    esac
  done
  sudo systemctl daemon-reload
  save_state
}

configure_selected() {
  local role uuid
  for role in "${SELECTED_ROLES[@]}"; do
    case "$role" in
      llm) uuid="$LLM_GPU_UUID"; persist_gpu_dropin llm "$uuid"; run_core configure llm ;;
      asr) uuid="$ASR_GPU_UUID"; persist_gpu_dropin asr "$uuid"; run_core configure asr ;;
      tts) configure_qwen ;;
      pyannote) configure_pyannote ;;
    esac
  done
  save_state
}

self_test() {
  local test_dir
  test_dir="$(mktemp -d /tmp/kienzlefon-ai-v2.selftest.XXXXXX)"
  write_core_payload > "$test_dir/core.sh"
  write_qwen_payload > "$test_dir/qwen.sh"
  write_diarization_server > "$test_dir/diarization_server.py"
  bash -n "$test_dir/core.sh"
  bash -n "$test_dir/qwen.sh"
  python3 -m py_compile "$test_dir/diarization_server.py"
  grep -Fq 'Qwen_Qwen3.5-9B-Q6_K.gguf' "$test_dir/core.sh"
  grep -Fq '073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef' "$test_dir/core.sh"
  grep -Fq 'context_size = 131072' "$test_dir/core.sh"
  grep -Fq -- '--int8' "$test_dir/qwen.sh"
  grep -Fq 'uncle_fu' "$test_dir/qwen.sh"
  grep -Fq '328ab9cb241774572bb59917af199bdf64a17227' "$test_dir/qwen.sh"
  grep -Fq 'pyannote/speaker-diarization-community-1' "$test_dir/diarization_server.py"
  grep -Fq 'STATE_TTS_PORT' "$0"
  grep -Fq '20-kienzlefon-v2-runtime.conf' "$0"
  grep -Fq 'kienzlefon-ai-asr-backend.service.d' "$0"
  ! grep -Eq 'HF_TOKEN=hf_[A-Za-z0-9]+' "$0"
  cat > "$test_dir/state.conf" <<'EOF'
enabled_roles=llm,tts
llm_gpu_uuid=GPU-test-llm
tts_gpu_uuid=GPU-test-tts
bind_address=127.0.0.9
llm_port=18080
asr_port=18178
asr_backend_port=18179
asr_backend_bind_address=0.0.0.0
tts_port=18182
pyannote_port=18183
EOF
  (
    BIND_ADDRESS="127.0.0.1"; LLM_PORT="8080"; ASR_PORT="8178"
    ASR_BACKEND_PORT="8179"; ASR_BACKEND_BIND_ADDRESS="127.0.0.1"; TTS_PORT="8182"; PYANNOTE_PORT="8183"
    BIND_EXPLICIT="n"; LLM_PORT_EXPLICIT="n"; ASR_PORT_EXPLICIT="n"
    ASR_BACKEND_PORT_EXPLICIT="n"; ASR_BACKEND_BIND_EXPLICIT="n"; TTS_PORT_EXPLICIT="n"; PYANNOTE_PORT_EXPLICIT="n"
    load_state "$test_dir/state.conf"
    [[ "$BIND_ADDRESS" == "127.0.0.9" && "$LLM_PORT" == "18080" ]]
    [[ "$ASR_PORT" == "18178" && "$ASR_BACKEND_PORT" == "18179" ]]
    [[ "$ASR_BACKEND_BIND_ADDRESS" == "0.0.0.0" ]]
    [[ "$TTS_PORT" == "18182" && "$PYANNOTE_PORT" == "18183" ]]
    [[ "$STATE_ENABLED_ROLES" == "llm,tts" && "$STATE_TTS_GPU_UUID" == "GPU-test-tts" ]]
  )
  (
    TTS_PORT="28182"; TTS_PORT_EXPLICIT="y"
    load_state "$test_dir/state.conf"
    [[ "$TTS_PORT" == "28182" ]]
  )
  (
    SELECTED_ROLES=(llm asr tts)
    ROLE_ALL_SELECTED="y"
    WITH_PYANNOTE="y"
    NON_INTERACTIVE="y"
    resolve_roles
    contains_role pyannote "${SELECTED_ROLES[@]}"
  )
  (
    SELECTED_ROLES=(llm asr tts)
    ROLE_ALL_SELECTED="n"
    WITH_PYANNOTE=""
    NON_INTERACTIVE="y"
    resolve_roles
    ! contains_role pyannote "${SELECTED_ROLES[@]}"
  )
  rm -rf -- "$test_dir"
  printf 'Kienzlefon AI Installer 2.0 self-test: ok\n'
}

render_payloads() {
  [[ -n "$RENDER_PAYLOADS" && "$RENDER_PAYLOADS" == /* ]] || die "--render-payloads verlangt einen absoluten Pfad."
  [[ ! -e "$RENDER_PAYLOADS" ]] || die "Renderziel existiert bereits."
  install -d -m 0755 "$RENDER_PAYLOADS"
  write_core_payload > "$RENDER_PAYLOADS/core.sh"
  write_qwen_payload > "$RENDER_PAYLOADS/qwen.sh"
  write_diarization_server > "$RENDER_PAYLOADS/diarization_server.py"
  chmod 0755 "$RENDER_PAYLOADS/core.sh" "$RENDER_PAYLOADS/qwen.sh"
  printf 'Payloads gerendert: %s\n' "$RENDER_PAYLOADS"
}

main() {
  parse_args "$@"
  case "$ACTION" in self-test) self_test; return ;; render-payloads) render_payloads; return ;; esac
  load_state
  resolve_roles
  require_cuda_platform
  if [[ "$ACTION" == "install" || "$ACTION" == "configure" ]]; then resolve_gpus; fi
  prepare_payloads
  case "$ACTION" in
    install) install_selected ;;
    configure) configure_selected ;;
    uninstall)
      local role
      for role in "${SELECTED_ROLES[@]}"; do uninstall_role "$role"; done
      save_state
      ;;
    start|stop|restart|status|test)
      local role
      for role in "${SELECTED_ROLES[@]}"; do service_action "$ACTION" "$role"; done
      if [[ "$ACTION" == "status" ]] && contains_role tts "${SELECTED_ROLES[@]}"; then check_piper_fallback; fi
      ;;
  esac
}

write_core_payload() {
  cat <<'__KZF_CORE_V2_PAYLOAD__'
#!/usr/bin/env bash
# install-kienzlefon-ai.sh
# Kienzlefon AI resident services installer for macOS Apple Silicon and Ubuntu Linux NVIDIA/CUDA
# Version: 2.0
#
# Examples:
#   ./install-kienzlefon-ai.sh --role all
#   ./install-kienzlefon-ai.sh --role llm --llm-slots 3 --llm-context 131072 --llm-kv-cache q8_0
#   ./install-kienzlefon-ai.sh --role asr
#   ./install-kienzlefon-ai.sh --action configure --role asr --asr-frame-threshold 20
#   ./install-kienzlefon-ai.sh --action status
#   ./install-kienzlefon-ai.sh --action test
#   ./install-kienzlefon-ai.sh --action uninstall --role asr
#   ./install-kienzlefon-ai.sh --action uninstall
#
# Managed paths:
#   /opt/kienzlefon-ai
#   /etc/kienzlefon-ai
#   /var/log/kienzlefon-ai
#   /Library/LaunchDaemons/de.kienzlefon.ai.*.plist (macOS)
#   /etc/systemd/system/kienzlefon-ai-*.service (Ubuntu)

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

INSTALLER_VERSION="2.0"
PREFIX="/opt/kienzlefon-ai-v2"
CONFIG_DIR="/etc/kienzlefon-ai"
CONFIG_FILE="${CONFIG_DIR}/kienzlefon-ai-v2.toml"
VERSIONS_FILE="${CONFIG_DIR}/versions-v2.conf"
LOG_DIR="/var/log/kienzlefon-ai-v2"
PLIST_DIR="/Library/LaunchDaemons"
SYSTEMD_DIR="/etc/systemd/system"
PLATFORM=""
ACCELERATOR=""
SERVICE_MANAGER=""
ROOT_GROUP=""
BREW_PREFIX=""
BREW_BIN=""
PYTHON=""
DOWNLOAD_DIR="${PREFIX}/downloads"

ACTION="install"
SELECTED_ROLES=()
BIND_OVERRIDE=""
CONFIRM_NONLOOPBACK=0
NO_START=0
SKIP_TESTS=0
LLM_PORT_OVERRIDE=""
ASR_PORT_OVERRIDE=""
ASR_BACKEND_PORT_OVERRIDE=""
ASR_BACKEND_BIND_OVERRIDE=""
ASR_FRAME_THRESHOLD_OVERRIDE=""
CONFIRM_ASR_BACKEND_NETWORK_EXPOSURE=0
TTS_PORT_OVERRIDE=""
LLM_CONTEXT_OVERRIDE=""
LLM_SLOTS_OVERRIDE=""
LLM_KV_CACHE_OVERRIDE=""
PIPER_WORKERS_OVERRIDE=""
PIPER_LENGTH_SCALE_OVERRIDE=""

# Preserve the exact invocation before option parsing so a Rosetta-launched
# shell can transparently re-exec this installer as native arm64.
ORIGINAL_ARGS=("$@")
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "$0")"

VALID_ROLES=(llm asr)

log()  { printf '[kienzlefon-ai] %s\n' "$*"; }
warn() { printf '[kienzlefon-ai] WARNUNG: %s\n' "$*" >&2; }
die()  { printf '[kienzlefon-ai] FEHLER: %s\n' "$*" >&2; exit 1; }

on_error() {
    local rc=$? cmd="${BASH_COMMAND:-?}"
    printf '[kienzlefon-ai] Abbruch in Zeile %s (Exit %s). Befehl: %s\n' "${BASH_LINENO[0]:-?}" "$rc" "$cmd" >&2
    if [[ "${PLATFORM:-}" == "macos" ]] 2>/dev/null && command -v launchctl >/dev/null 2>&1; then
        launchctl error "$rc" 2>/dev/null | sed 's/^/[kienzlefon-ai] launchctl: /' >&2 || true
    fi
    exit "$rc"
}
trap on_error ERR

usage() {
    cat <<'EOF'
Kienzlefon-AI Multiplatform-Installer

Unterstützt in dieser Version:
  - macOS auf Apple Silicon (arm64): Metal / MLX
  - Ubuntu Linux x86_64 mit NVIDIA: CUDA

Noch nicht unterstützt:
  - AMD/ROCm/HIP (Architektur dafür vorbereitet; folgt später)
  - CPU-only für LLM/ASR

Aufruf:
  install-kienzlefon-ai.sh --role ROLLE [Optionen]
  install-kienzlefon-ai.sh --action configure|start|stop|restart|status|test|uninstall [--role ROLLE]

Rollen:
  llm
  asr
  tts
  all

ASR:
  Kienzlefon -> ws://<bind>:8178/v1/asr/stream -> eigener Adapter
              -> WhisperLiveKit standardmäßig auf 127.0.0.1:8179 -> Whisper large-v3
  Ein direkter WhisperLiveKit-Netzzugriff ist nur als ausdrücklich bestätigte
  Entwicklungsoption vorgesehen.
  macOS:  mlx-whisper / MLX / Metal
  Ubuntu: faster-whisper / CUDA

Optionen:
  --action ACTION                 install (Standard), configure, start, stop, restart,
                                  status, test, uninstall
  --role ROLLE                    Mehrfach verwendbar; bei Erstinstallation erforderlich
  --bind ADRESSE                  Standard 127.0.0.1
  --confirm-nonloopback-bind      Erforderlich für andere Adressen als 127.0.0.1/::1
  --llm-port PORT                 Standard 8080
  --llm-slots ANZAHL              Parallele, gleich große LLM-Slots (1 bis 4)
                                  Ubuntu/CUDA-Standard: 3; macOS-Standard: 4
  --llm-context TOKENS            Gesamtkontext über alle Slots
                                  Ubuntu/CUDA-Standard: 131072; macOS: 32768
  --llm-kv-cache TYP              f16 oder q8_0
                                  Ubuntu/CUDA-Standard: q8_0; macOS: f16
  --asr-port PORT                 Kienzlefon Streaming-ASR, Standard 8178
  --asr-backend-port PORT         WhisperLiveKit, Standard 8179
  --asr-backend-bind ADRESSE      WhisperLiveKit-Bindung: 127.0.0.1 (Standard)
                                  oder 0.0.0.0 für alle IPv4-Schnittstellen
  --confirm-asr-backend-network-exposure
                                  Erforderlich für 0.0.0.0
  --asr-frame-threshold FRAMES    AlignAtt, Standard 25; niedriger ist schneller,
                                  höher genauer (zulässig: 1 bis 1500)
  --tts-port PORT                 Standard 8181
  --piper-workers ANZAHL          Standard 4
  --piper-length-scale WERT       Standard 1.1
  --no-start                      Dienste nach Installation nicht starten
  --skip-tests                    Mindesttests nach Installation überspringen
  --version                       Installerversion anzeigen
  -h, --help                      Hilfe anzeigen

Configure:
  --action configure aktualisiert eine vorhandene Installation ohne Downloads,
  Paketinstallation, Modellinstallation oder Builds. Geändert werden nur die
  Konfiguration und das verwaltete Startskript; anschließend werden ausschließlich
  die betroffenen bzw. mit --role ausgewählten Dienste neu gestartet.

Uninstall:
  --action uninstall --role asr   Nur ASR inklusive WhisperLiveKit/Modellen entfernen
  --action uninstall --role llm   Nur LLM inklusive llama.cpp/Qwen-Modell entfernen
  --action uninstall --role tts   Nur Piper inklusive Stimme/venv entfernen
  --action uninstall              Gesamte von DIESEM Installer verwaltete Installation entfernen

  Ein Rollen-Uninstall aktualisiert enabled_roles in der TOML. Werden keine Rollen
  mehr übrig gelassen, werden auch gemeinsame Dateien, Konfiguration und Logs entfernt.
  Nicht entfernt werden Homebrew-/APT-Pakete, NVIDIA-Treiber, CUDA oder andere
  Installationen außerhalb /opt/kienzlefon-ai, /etc/kienzlefon-ai und
  /var/log/kienzlefon-ai. Insbesondere /opt/kienzlefon/qwen3-tts bleibt unberührt.

Linux/CUDA-Voraussetzungen:
  - Ubuntu x86_64
  - Python 3.11, 3.12 oder 3.13 mit venv-Unterstützung
  - NVIDIA-Treiber funktionsfähig (nvidia-smi)
  - CUDA Toolkit mit nvcc bereits installiert
  - Treiber/CUDA werden geprüft, aber nicht vom Installer verändert
  - CUDA wird nur für llm/asr verlangt; Piper bleibt CPU-basiert

macOS-Voraussetzungen:
  - Apple Silicon; Rosetta-Start wird automatisch in native arm64-Ausführung umgeschaltet
  - Xcode Command Line Tools
  - Homebrew

Der Installer bindet Dienste standardmäßig ausschließlich an 127.0.0.1.
EOF
}

is_valid_role() {
    local needle="$1" r
    for r in "${VALID_ROLES[@]}"; do
        [[ "$needle" == "$r" ]] && return 0
    done
    return 1
}

add_role() {
    local role="$1" r
    if [[ "$role" == "all" ]]; then
        for r in "${VALID_ROLES[@]}"; do add_role "$r"; done
        return
    fi
    is_valid_role "$role" || die "Unbekannte Rolle: $role"
    for r in "${SELECTED_ROLES[@]:-}"; do
        [[ "$r" == "$role" ]] && return
    done
    SELECTED_ROLES+=("$role")
}

require_uint_port() {
    local name="$1" value="$2"
    [[ "$value" =~ ^[0-9]+$ ]] || die "$name muss eine ganze Zahl sein."
    (( value >= 1 && value <= 65535 )) || die "$name muss zwischen 1 und 65535 liegen."
}

while (($#)); do
    case "$1" in
        --action) [[ $# -ge 2 ]] || die "Wert für --action fehlt."; ACTION="$2"; shift 2 ;;
        --role) [[ $# -ge 2 ]] || die "Wert für --role fehlt."; add_role "$2"; shift 2 ;;
        --bind) [[ $# -ge 2 ]] || die "Wert für --bind fehlt."; BIND_OVERRIDE="$2"; shift 2 ;;
        --confirm-nonloopback-bind) CONFIRM_NONLOOPBACK=1; shift ;;
        --llm-port) LLM_PORT_OVERRIDE="${2:-}"; shift 2 ;;
        --llm-slots) [[ $# -ge 2 ]] || die "Wert für --llm-slots fehlt."; LLM_SLOTS_OVERRIDE="$2"; shift 2 ;;
        --llm-kv-cache) [[ $# -ge 2 ]] || die "Wert für --llm-kv-cache fehlt."; LLM_KV_CACHE_OVERRIDE="$2"; shift 2 ;;
        --asr-port) ASR_PORT_OVERRIDE="${2:-}"; shift 2 ;;
        --asr-backend-port) ASR_BACKEND_PORT_OVERRIDE="${2:-}"; shift 2 ;;
        --asr-backend-bind) [[ $# -ge 2 ]] || die "Wert für --asr-backend-bind fehlt."; ASR_BACKEND_BIND_OVERRIDE="$2"; shift 2 ;;
        --confirm-asr-backend-network-exposure) CONFIRM_ASR_BACKEND_NETWORK_EXPOSURE=1; shift ;;
        --asr-frame-threshold) [[ $# -ge 2 ]] || die "Wert für --asr-frame-threshold fehlt."; ASR_FRAME_THRESHOLD_OVERRIDE="$2"; shift 2 ;;
        --tts-port) TTS_PORT_OVERRIDE="${2:-}"; shift 2 ;;
        --llm-context) LLM_CONTEXT_OVERRIDE="${2:-}"; shift 2 ;;
        --piper-workers) PIPER_WORKERS_OVERRIDE="${2:-}"; shift 2 ;;
        --piper-length-scale) PIPER_LENGTH_SCALE_OVERRIDE="${2:-}"; shift 2 ;;
        --no-start) NO_START=1; shift ;;
        --skip-tests) SKIP_TESTS=1; shift ;;
        --version) printf '%s\n' "$INSTALLER_VERSION"; exit 0 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1" ;;
    esac
done

case "$ACTION" in install|configure|start|stop|restart|status|test|uninstall) ;; *) die "Ungültige Aktion: $ACTION" ;; esac
[[ -z "$LLM_PORT_OVERRIDE" ]] || require_uint_port "LLM-Port" "$LLM_PORT_OVERRIDE"
if [[ -n "$LLM_SLOTS_OVERRIDE" ]]; then
    [[ "$LLM_SLOTS_OVERRIDE" =~ ^[0-9]+$ ]] || die "--llm-slots muss ganzzahlig sein."
    (( LLM_SLOTS_OVERRIDE >= 1 && LLM_SLOTS_OVERRIDE <= 4 )) || die "--llm-slots muss zwischen 1 und 4 liegen."
fi
case "$LLM_KV_CACHE_OVERRIDE" in
    ""|f16|q8_0) ;;
    *) die "--llm-kv-cache erlaubt nur f16 oder q8_0." ;;
esac
[[ -z "$ASR_PORT_OVERRIDE" ]] || require_uint_port "ASR-Port" "$ASR_PORT_OVERRIDE"
[[ -z "$ASR_BACKEND_PORT_OVERRIDE" ]] || require_uint_port "ASR-Backend-Port" "$ASR_BACKEND_PORT_OVERRIDE"
case "$ASR_BACKEND_BIND_OVERRIDE" in
    ""|127.0.0.1|0.0.0.0) ;;
    *) die "--asr-backend-bind erlaubt nur 127.0.0.1 oder 0.0.0.0." ;;
esac
if [[ -n "$ASR_FRAME_THRESHOLD_OVERRIDE" ]]; then
    [[ "$ASR_FRAME_THRESHOLD_OVERRIDE" =~ ^[0-9]+$ ]] || die "--asr-frame-threshold muss ganzzahlig sein."
    (( ASR_FRAME_THRESHOLD_OVERRIDE >= 1 && ASR_FRAME_THRESHOLD_OVERRIDE <= 1500 )) || die "--asr-frame-threshold muss zwischen 1 und 1500 liegen."
fi
[[ -z "$TTS_PORT_OVERRIDE" ]] || require_uint_port "TTS-Port" "$TTS_PORT_OVERRIDE"
[[ -z "$LLM_CONTEXT_OVERRIDE" || "$LLM_CONTEXT_OVERRIDE" =~ ^[0-9]+$ ]] || die "--llm-context muss ganzzahlig sein."
[[ -z "$PIPER_WORKERS_OVERRIDE" || "$PIPER_WORKERS_OVERRIDE" =~ ^[0-9]+$ ]] || die "--piper-workers muss ganzzahlig sein."
[[ -z "$PIPER_LENGTH_SCALE_OVERRIDE" || "$PIPER_LENGTH_SCALE_OVERRIDE" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--piper-length-scale ist ungültig."

detect_platform() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"
    case "$os" in
        Darwin)
            # `uname -m` reports x86_64 when the invoking terminal/shell is
            # translated by Rosetta, even though the physical Mac is Apple
            # Silicon. Detect that case before rejecting the platform.
            local translated hw_arm64
            translated="$(sysctl -in sysctl.proc_translated 2>/dev/null || printf '0')"
            hw_arm64="$(sysctl -in hw.optional.arm64 2>/dev/null || printf '0')"

            if [[ "$arch" == "x86_64" && ( "$translated" == "1" || "$hw_arm64" == "1" ) ]]; then
                [[ "${KIENZLEFON_NATIVE_REEXEC:-0}" != "1" ]] || \
                    die "Apple-Silicon-Hardware erkannt, aber der native arm64-Neustart ist fehlgeschlagen."
                [[ -x /usr/bin/arch && -x /bin/bash ]] || \
                    die "Apple Silicon erkannt, aber /usr/bin/arch oder /bin/bash fehlt."
                log "Rosetta/x86_64-Prozess auf Apple Silicon erkannt; starte Installer automatisch nativ als arm64 neu ..."
                exec /usr/bin/env KIENZLEFON_NATIVE_REEXEC=1 \
                    /usr/bin/arch -arm64 /bin/bash "$SCRIPT_PATH" "${ORIGINAL_ARGS[@]}"
            fi

            [[ "$arch" == "arm64" ]] || die "macOS wird nur auf Apple Silicon unterstützt; Prozessarchitektur: $arch."
            [[ "$(sysctl -in sysctl.proc_translated 2>/dev/null || printf '0')" != "1" ]] || \
                die "Native arm64-Ausführung konnte nicht hergestellt werden."
            [[ "$EUID" -ne 0 ]] || die "Unter macOS nicht als root ausführen; Homebrew darf nicht als root laufen."
            PLATFORM="macos"
            ACCELERATOR="metal"
            SERVICE_MANAGER="launchd"
            ROOT_GROUP="wheel"
            INSTALL_USER="$(id -un)"
            INSTALL_GROUP="$(id -gn)"
            if [[ "$ACTION" == "uninstall" ]]; then
                # Eine Deinstallation darf nicht daran scheitern, dass Homebrew oder
                # Xcode Command Line Tools inzwischen bereits entfernt wurden.
                BREW_PREFIX="/opt/homebrew"
                [[ -x /opt/homebrew/bin/brew ]] && BREW_BIN="/opt/homebrew/bin/brew" || BREW_BIN=""
                export PATH="${BREW_PREFIX}/bin:${BREW_PREFIX}/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
            else
                command -v xcode-select >/dev/null 2>&1 || die "xcode-select fehlt."
                xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools fehlen. Installieren mit: xcode-select --install"

                # Prefer the native Apple-Silicon Homebrew installation explicitly.
                if [[ -x /opt/homebrew/bin/brew ]]; then
                    BREW_BIN="/opt/homebrew/bin/brew"
                elif command -v brew >/dev/null 2>&1; then
                    BREW_BIN="$(command -v brew)"
                else
                    die "Homebrew fehlt. Bitte zuerst Homebrew installieren."
                fi
                BREW_PREFIX="$($BREW_BIN --prefix)"
                [[ "$BREW_PREFIX" == "/opt/homebrew" ]] || \
                    die "Auf Apple Silicon wird natives Homebrew unter /opt/homebrew erwartet; gefunden: $BREW_PREFIX. Vermutlich ist nur Intel-Homebrew installiert."
                export PATH="${BREW_PREFIX}/bin:${BREW_PREFIX}/sbin:/usr/bin:/bin:/usr/sbin:/sbin"
            fi
            ;;
        Linux)
            [[ -r /etc/os-release ]] || die "/etc/os-release fehlt; Ubuntu konnte nicht erkannt werden."
            # shellcheck disable=SC1091
            . /etc/os-release
            [[ "${ID:-}" == "ubuntu" ]] || die "Linux wird derzeit nur als Ubuntu unterstützt; erkannt: ${ID:-unbekannt}."
            [[ "$arch" == "x86_64" ]] || die "Ubuntu/CUDA wird derzeit nur auf x86_64 unterstützt; erkannt: $arch."
            [[ "$EUID" -ne 0 || "$ACTION" == "configure" ]] || \
                die "Bitte als normaler sudo-Benutzer ausführen, nicht direkt als root."
            PLATFORM="ubuntu"
            ACCELERATOR="cuda"
            SERVICE_MANAGER="systemd"
            ROOT_GROUP="root"
            INSTALL_USER="$(id -un)"
            INSTALL_GROUP="$(id -gn)"
            command -v sudo >/dev/null 2>&1 || die "sudo fehlt."
            command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl fehlt."
            export PATH="/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
            ;;
        *) die "Nicht unterstütztes Betriebssystem: $os" ;;
    esac
    log "Plattform erkannt: ${PLATFORM} / ${arch}; Beschleunigerprofil: ${ACCELERATOR}; Service-Manager: ${SERVICE_MANAGER}"
}

detect_platform

if [[ -n "$BIND_OVERRIDE" && "$BIND_OVERRIDE" != "127.0.0.1" && "$BIND_OVERRIDE" != "::1" ]]; then
    (( CONFIRM_NONLOOPBACK == 1 )) || die "Nicht-lokale Bind-Adresse erfordert --confirm-nonloopback-bind."
fi
if [[ "$BIND_OVERRIDE" == "0.0.0.0" || "$BIND_OVERRIDE" == "::" ]]; then
    (( CONFIRM_NONLOOPBACK == 1 )) || die "Öffentliche Wildcard-Bindung wurde nicht bestätigt."
    warn "Wildcard-Bindung aktiviert. Firewall und Netzsegmentierung eigenständig prüfen."
fi
if [[ "$ASR_BACKEND_BIND_OVERRIDE" == "0.0.0.0" ]]; then
    (( CONFIRM_ASR_BACKEND_NETWORK_EXPOSURE == 1 )) || \
        die "Direkter WhisperLiveKit-Netzzugriff erfordert --confirm-asr-backend-network-exposure."
    warn "WhisperLiveKit wird direkt im Netz verfügbar. Nur für die Entwicklung verwenden und den Port per Firewall auf vertrauenswürdige Quelladressen begrenzen."
fi

need_sudo() {
    sudo -v
}

select_supported_python() {
    local candidate version
    if [[ "$PLATFORM" == "macos" ]]; then
        candidate="${BREW_PREFIX}/opt/python@3.13/bin/python3.13"
        [[ -x "$candidate" ]] || return 1
        PYTHON="$candidate"
        return 0
    fi

    # WhisperLiveKit 0.2.24 verlangt Python >=3.11,<3.14. Unter Ubuntu
    # nutzen wir eine bereits vorhandene passende Python-Version und ändern
    # bewusst nicht die Distribution/PPA-Konfiguration des Systems.
    for candidate in python3.13 python3.12 python3.11 python3; do
        candidate="$(command -v "$candidate" 2>/dev/null || true)"
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        if "$candidate" - <<'PYCHECK' >/dev/null 2>&1
import sys
import venv
raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)
PYCHECK
        then
            PYTHON="$candidate"
            version="$($PYTHON -c 'import sys; print(sys.version.split()[0])')"
            log "Verwende Python $version: $PYTHON"
            return 0
        fi
    done
    return 1
}

install_platform_dependencies() {
    log "Prüfe Build- und Laufzeitwerkzeuge ..."
    if [[ "$PLATFORM" == "macos" ]]; then
        local packages=(cmake ninja git python@3.13 jq ffmpeg)
        "$BREW_BIN" install "${packages[@]}"
    else
        need_sudo
        sudo apt-get update
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
            build-essential cmake ninja-build git python3 python3-venv python3-pip python3-dev \
            jq ffmpeg curl ca-certificates lsof espeak-ng pkg-config file \
            libssl-dev libcurl4-openssl-dev
    fi

    select_supported_python || die "Keine geeignete Python-Version gefunden. WhisperLiveKit 0.2.24 benötigt Python >=3.11,<3.14. Installiere unter Ubuntu Python 3.11, 3.12 oder 3.13 einschließlich venv-Unterstützung."
    "$PYTHON" - <<'PYCHECK'
import sys
import venv
if not ((3, 11) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(f"WhisperLiveKit benötigt Python >=3.11,<3.14; vorhanden: {sys.version.split()[0]}")
print("Python:", sys.version.split()[0])
PYCHECK
}

set_python_for_management() {
    select_supported_python || PYTHON=""
}

ensure_managed_dirs() {
    need_sudo
    sudo install -d -m 0755 -o "$INSTALL_USER" -g "$INSTALL_GROUP" \
        "$PREFIX" "$PREFIX/bin" "$PREFIX/src" "$PREFIX/models" "$PREFIX/python" \
        "$PREFIX/scripts" "$DOWNLOAD_DIR"
    sudo install -d -m 0755 -o root -g "$ROOT_GROUP" "$CONFIG_DIR"
    sudo install -d -m 0750 -o "$INSTALL_USER" -g "$INSTALL_GROUP" "$LOG_DIR"
}

write_versions_file_if_missing() {
    if [[ -e "$VERSIONS_FILE" ]]; then
        log "Vorhandene Versionsdatei bleibt erhalten: $VERSIONS_FILE"
        return
    fi
    local tmp
    tmp="$(mktemp)"
    cat >"$tmp" <<'EOF'
# Kienzlefon-AI feste Quellen und Prüfsummen
INSTALLER_VERSION=2.0
LLAMA_CPP_REPOSITORY=https://github.com/ggml-org/llama.cpp.git
LLAMA_CPP_REF=b9637
WHISPERLIVEKIT_VERSION=0.2.24
WHISPERLIVEKIT_WHEEL_SHA256=f11ff4c74f3efe11d09b50a08cfd6c33ed74fed4a397429d70254ada3feeeda6
MLX_VERSION=0.32.0
MLX_WHISPER_VERSION=0.4.3
WHISPER_MLX_REPOSITORY=mlx-community/whisper-large-v3-mlx
WHISPER_MLX_REVISION=49e6aa286ad60c14352c404340ded53710378a11
WHISPER_MLX_WEIGHTS_FILENAME=weights.npz
WHISPER_MLX_WEIGHTS_SHA256=05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d
WHISPER_MLX_CONFIG_FILENAME=config.json
WHISPER_MLX_CONFIG_SHA256=34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3
WHISPER_CUDA_REPOSITORY=Systran/faster-whisper-large-v3
WHISPER_CUDA_REVISION=edaa852ec7e145841d8ffdb056a99866b5f0a478
WHISPER_CUDA_MODEL_SHA256=69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1
WHISPER_OPENAI_LARGE_V3_SHA256=e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb
FASTER_WHISPER_VERSION=1.2.1
PIPER_TTS_VERSION=1.6.0
PIPER_MACOS_ARM64_WHEEL_SHA256=b37ddd191b31995fbe981d5900df9c15888cccf427bff8e0b368cc95489fd60a
PIPER_LINUX_X86_64_WHEEL_SHA256=3120d5cc45e07fb99bdede8feef85116fd45bf488aa1d89c7b1aefb657d38683
QWEN_GGUF_REPOSITORY=bartowski/Qwen_Qwen3.5-9B-GGUF
QWEN_GGUF_REVISION=2dcd842
QWEN_GGUF_FILENAME=Qwen_Qwen3.5-9B-Q6_K.gguf
QWEN_GGUF_SHA256=073a9275e65d9c8cd2819cf5f77b99fbaa6e87ba591da6bbaa86ec073a64bfef
PIPER_VOICE_REPOSITORY=rhasspy/piper-voices
PIPER_VOICE_REVISION=v1.0.0
PIPER_VOICE_PATH=de/de_DE/thorsten/high/de_DE-thorsten-high.onnx
PIPER_VOICE_SHA256=9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1
PIPER_VOICE_CONFIG_PATH=de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json
PIPER_VOICE_CONFIG_MD5=e81686e00a9d825e2488ead660bec6fd
EOF
    sudo install -m 0644 -o root -g "$ROOT_GROUP" "$tmp" "$VERSIONS_FILE"
    rm -f "$tmp"
}

load_versions_file() {
    [[ -r "$VERSIONS_FILE" ]] || die "Versionsdatei fehlt: $VERSIONS_FILE"
    local key value
    while IFS='=' read -r key value; do
        [[ -n "$key" && "$key" != \#* ]] || continue
        case "$key" in
            LLAMA_CPP_REPOSITORY|LLAMA_CPP_REF|WHISPERLIVEKIT_VERSION|WHISPERLIVEKIT_WHEEL_SHA256|MLX_VERSION|MLX_WHISPER_VERSION|WHISPER_MLX_REPOSITORY|WHISPER_MLX_REVISION|WHISPER_MLX_WEIGHTS_FILENAME|WHISPER_MLX_WEIGHTS_SHA256|WHISPER_MLX_CONFIG_FILENAME|WHISPER_MLX_CONFIG_SHA256|WHISPER_CUDA_REPOSITORY|WHISPER_CUDA_REVISION|WHISPER_CUDA_MODEL_SHA256|WHISPER_OPENAI_LARGE_V3_SHA256|FASTER_WHISPER_VERSION|PIPER_TTS_VERSION|PIPER_MACOS_ARM64_WHEEL_SHA256|PIPER_LINUX_X86_64_WHEEL_SHA256|QWEN_GGUF_REPOSITORY|QWEN_GGUF_REVISION|QWEN_GGUF_FILENAME|QWEN_GGUF_SHA256|PIPER_VOICE_REPOSITORY|PIPER_VOICE_REVISION|PIPER_VOICE_PATH|PIPER_VOICE_SHA256|PIPER_VOICE_CONFIG_PATH|PIPER_VOICE_CONFIG_MD5)
                printf -v "$key" '%s' "$value"
                ;;
        esac
    done < "$VERSIONS_FILE"

    local required=(LLAMA_CPP_REPOSITORY LLAMA_CPP_REF WHISPERLIVEKIT_VERSION WHISPERLIVEKIT_WHEEL_SHA256 MLX_VERSION MLX_WHISPER_VERSION WHISPER_MLX_REPOSITORY WHISPER_MLX_REVISION WHISPER_MLX_WEIGHTS_FILENAME WHISPER_MLX_WEIGHTS_SHA256 WHISPER_MLX_CONFIG_FILENAME WHISPER_MLX_CONFIG_SHA256 WHISPER_CUDA_REPOSITORY WHISPER_CUDA_REVISION WHISPER_CUDA_MODEL_SHA256 WHISPER_OPENAI_LARGE_V3_SHA256 FASTER_WHISPER_VERSION PIPER_TTS_VERSION PIPER_MACOS_ARM64_WHEEL_SHA256 PIPER_LINUX_X86_64_WHEEL_SHA256 QWEN_GGUF_REPOSITORY QWEN_GGUF_REVISION QWEN_GGUF_FILENAME QWEN_GGUF_SHA256 PIPER_VOICE_REPOSITORY PIPER_VOICE_REVISION PIPER_VOICE_PATH PIPER_VOICE_SHA256 PIPER_VOICE_CONFIG_PATH PIPER_VOICE_CONFIG_MD5)
    local var
    for var in "${required[@]}"; do
        [[ -n "${!var:-}" ]] || die "Fehlender Schlüssel in versions.conf: $var. Falls dies eine Datei aus Installer 0.1.0 ist, bitte vor dem ersten Test entfernen; automatische Versionsmigration folgt erst in der Härtungsphase."
    done
}

roles_csv() {
    local IFS=,
    printf '%s' "$*"
}

write_or_update_config() {
    local selected_csv tmp asr_backend asr_model_path
    selected_csv="$(roles_csv "${SELECTED_ROLES[@]:-}")"
    if [[ "$PLATFORM" == "macos" ]]; then
        asr_backend="mlx-whisper"
        asr_model_path="${PREFIX}/models/whisper-large-v3-mlx"
    else
        asr_backend="faster-whisper"
        asr_model_path="${PREFIX}/models/whisper-large-v3-cuda"
    fi
    tmp="$(mktemp)"
    CONFIG_PATH="$CONFIG_FILE" \
    SELECTED_ROLES_CSV="$selected_csv" \
    BIND_OVERRIDE="$BIND_OVERRIDE" \
    LLM_PORT_OVERRIDE="$LLM_PORT_OVERRIDE" \
    LLM_SLOTS_OVERRIDE="$LLM_SLOTS_OVERRIDE" \
    LLM_KV_CACHE_OVERRIDE="$LLM_KV_CACHE_OVERRIDE" \
    ASR_PORT_OVERRIDE="$ASR_PORT_OVERRIDE" \
    ASR_BACKEND_PORT_OVERRIDE="$ASR_BACKEND_PORT_OVERRIDE" \
    ASR_BACKEND_BIND_OVERRIDE="$ASR_BACKEND_BIND_OVERRIDE" \
    ASR_FRAME_THRESHOLD_OVERRIDE="$ASR_FRAME_THRESHOLD_OVERRIDE" \
    TTS_PORT_OVERRIDE="$TTS_PORT_OVERRIDE" \
    LLM_CONTEXT_OVERRIDE="$LLM_CONTEXT_OVERRIDE" \
    PIPER_WORKERS_OVERRIDE="$PIPER_WORKERS_OVERRIDE" \
    PIPER_LENGTH_SCALE_OVERRIDE="$PIPER_LENGTH_SCALE_OVERRIDE" \
    PLATFORM_ID="$PLATFORM" \
    ACCELERATOR_ID="$ACCELERATOR" \
    SERVICE_MANAGER_ID="$SERVICE_MANAGER" \
    ASR_BACKEND_TYPE="$asr_backend" \
    ASR_MODEL_PATH="$asr_model_path" \
    OUTPUT_PATH="$tmp" \
    "$PYTHON" - <<'PY'
import json
import os
import re
import tomllib
from pathlib import Path

config_path = Path(os.environ["CONFIG_PATH"])
out_path = Path(os.environ["OUTPUT_PATH"])
selected = [x for x in os.environ.get("SELECTED_ROLES_CSV", "").split(",") if x]
role_order = ["llm", "asr"]
model_root = "/opt/kienzlefon-ai/models"
platform_id = os.environ["PLATFORM_ID"]
accelerator_id = os.environ["ACCELERATOR_ID"]
service_manager_id = os.environ["SERVICE_MANAGER_ID"]
asr_backend_type = os.environ["ASR_BACKEND_TYPE"]
asr_model_path = os.environ["ASR_MODEL_PATH"]
new_llm_slots = 3 if accelerator_id == "cuda" else 4
new_llm_context_size = 131072 if accelerator_id == "cuda" else 32768
new_llm_kv_cache_type = "q8_0" if accelerator_id == "cuda" else "f16"

def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)

def set_top_level(src, key, value):
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    line = f"{key} = {toml_value(value)}"
    if pattern.search(src):
        return pattern.sub(line, src, count=1)
    first_section = re.search(r"(?m)^\[", src)
    pos = first_section.start() if first_section else len(src)
    return src[:pos] + line + "\n" + src[pos:]

def set_section_key(src, section, key, value):
    sec = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", src)
    if not sec:
        return src.rstrip() + f"\n\n[{section}]\n{key} = {toml_value(value)}\n"
    next_sec = re.search(r"(?m)^\[", src[sec.end():])
    end = sec.end() + (next_sec.start() if next_sec else len(src[sec.end():]))
    block = src[sec.end():end]
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    line = f"{key} = {toml_value(value)}"
    if pattern.search(block):
        block = pattern.sub(line, block, count=1)
    else:
        block = block.rstrip() + "\n" + line + "\n"
    return src[:sec.end()] + block + src[end:]

if config_path.exists():
    text = config_path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except Exception as exc:
        raise SystemExit(f"Vorhandene TOML-Konfiguration ist ungültig: {exc}")
    existing_roles = list(data.get("enabled_roles", []))
    if any(r in {"asr-turbo-live", "asr-large-live", "asr-large-post"} for r in existing_roles):
        existing_roles = [r for r in existing_roles if not r.startswith("asr-")]
        existing_roles.append("asr")
    merged = [r for r in role_order if r in set(existing_roles + selected)]
else:
    merged = selected
    text = f'''schema_version = 3
enabled_roles = {json.dumps(merged, ensure_ascii=False)}
bind_address = "127.0.0.1"

[runtime]
platform = "{platform_id}"
accelerator = "{accelerator_id}"
service_manager = "{service_manager_id}"

[llm]
port = 8080
model_path = "{model_root}/Qwen_Qwen3.5-9B-Q6_K.gguf"
model_alias = "qwen3.5-9b"
slots = {new_llm_slots}
context_size = {new_llm_context_size}
kv_cache_type = "{new_llm_kv_cache_type}"
continuous_batching = true
streaming = true
thinking = false

[asr]
port = 8178
protocol = "kienzlefon-asr-v1"
backend = "whisperlivekit"
backend_host = "127.0.0.1"
backend_bind_address = "127.0.0.1"
backend_port = 8179
backend_type = "{asr_backend_type}"
backend_policy = "simulstreaming"
frame_threshold = 25
beams = 1
decoder = "beam"
never_fire = false
model = "large-v3"
model_path = "{asr_model_path}"
language = "de"
pcm_input = true
diarization = false
require_hardware_acceleration = true
allow_cpu_fallback = false

[tts]
port = 8181
model_path = "{model_root}/de_DE-thorsten-high.onnx"
model_config_path = "{model_root}/de_DE-thorsten-high.onnx.json"
workers = 4
length_scale = 1.1
'''

text = set_top_level(text, "schema_version", 3)
text = set_top_level(text, "enabled_roles", merged)
text = set_section_key(text, "runtime", "platform", platform_id)
text = set_section_key(text, "runtime", "accelerator", accelerator_id)
text = set_section_key(text, "runtime", "service_manager", service_manager_id)

def ensure_section_key(src, section, key, value):
    sec = re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", src)
    if not sec:
        return set_section_key(src, section, key, value)
    next_sec = re.search(r"(?m)^\[", src[sec.end():])
    end = sec.end() + (next_sec.start() if next_sec else len(src[sec.end():]))
    if re.search(rf"(?m)^{re.escape(key)}\s*=", src[sec.end():end]):
        return src
    return set_section_key(src, section, key, value)

defaults = {
    ("llm", "port"): 8080,
    ("llm", "model_path"): f"{model_root}/Qwen_Qwen3.5-9B-Q6_K.gguf",
    ("llm", "model_alias"): "qwen3.5-9b",
    ("llm", "slots"): 4,
    ("llm", "context_size"): 32768,
    # Bei vorhandenen Konfigurationen bleibt ohne explizites Override das
    # bisherige F16-Verhalten erhalten. Neue CUDA-Installationen erhalten das
    # oben erzeugte, auf der RTX 3090 praktisch getestete Q8-Profil.
    ("llm", "kv_cache_type"): "f16",
    ("llm", "continuous_batching"): True,
    ("llm", "streaming"): True,
    ("llm", "thinking"): False,
    ("asr", "port"): 8178,
    ("asr", "protocol"): "kienzlefon-asr-v1",
    ("asr", "backend"): "whisperlivekit",
    ("asr", "backend_host"): "127.0.0.1",
    ("asr", "backend_bind_address"): "127.0.0.1",
    ("asr", "backend_port"): 8179,
    ("asr", "backend_type"): asr_backend_type,
    ("asr", "backend_policy"): "simulstreaming",
    ("asr", "frame_threshold"): 25,
    ("asr", "beams"): 1,
    ("asr", "decoder"): "beam",
    ("asr", "never_fire"): False,
    ("asr", "model"): "large-v3",
    ("asr", "model_path"): asr_model_path,
    ("asr", "language"): "de",
    ("asr", "pcm_input"): True,
    ("asr", "diarization"): False,
    ("asr", "require_hardware_acceleration"): True,
    ("asr", "allow_cpu_fallback"): False,
    ("tts", "port"): 8181,
    ("tts", "model_path"): f"{model_root}/de_DE-thorsten-high.onnx",
    ("tts", "model_config_path"): f"{model_root}/de_DE-thorsten-high.onnx.json",
    ("tts", "workers"): 4,
    ("tts", "length_scale"): 1.1,
}
for (section, key), value in defaults.items():
    text = ensure_section_key(text, section, key, value)

overrides = {
    (None, "bind_address"): os.environ.get("BIND_OVERRIDE", ""),
    ("llm", "port"): os.environ.get("LLM_PORT_OVERRIDE", ""),
    ("llm", "slots"): os.environ.get("LLM_SLOTS_OVERRIDE", ""),
    ("asr", "port"): os.environ.get("ASR_PORT_OVERRIDE", ""),
    ("asr", "backend_port"): os.environ.get("ASR_BACKEND_PORT_OVERRIDE", ""),
    ("asr", "backend_bind_address"): os.environ.get("ASR_BACKEND_BIND_OVERRIDE", ""),
    ("asr", "frame_threshold"): os.environ.get("ASR_FRAME_THRESHOLD_OVERRIDE", ""),
    ("tts", "port"): os.environ.get("TTS_PORT_OVERRIDE", ""),
    ("llm", "context_size"): os.environ.get("LLM_CONTEXT_OVERRIDE", ""),
    ("llm", "kv_cache_type"): os.environ.get("LLM_KV_CACHE_OVERRIDE", ""),
    ("tts", "workers"): os.environ.get("PIPER_WORKERS_OVERRIDE", ""),
    ("tts", "length_scale"): os.environ.get("PIPER_LENGTH_SCALE_OVERRIDE", ""),
}
for (section, key), raw in overrides.items():
    if raw == "":
        continue
    value = raw
    if key in {"port", "backend_port", "frame_threshold", "slots", "context_size", "workers"}:
        value = int(raw)
    elif key == "length_scale":
        value = float(raw)
    text = set_top_level(text, key, value) if section is None else set_section_key(text, section, key, value)

text = set_section_key(text, "runtime", "platform", platform_id)
text = set_section_key(text, "runtime", "accelerator", accelerator_id)
text = set_section_key(text, "runtime", "service_manager", service_manager_id)
text = set_section_key(text, "asr", "backend", "whisperlivekit")
final_cfg = tomllib.loads(text)
llm_cfg = final_cfg.get("llm", {})
kv_cache_type = llm_cfg.get("kv_cache_type")
if kv_cache_type not in {"f16", "q8_0"}:
    raise SystemExit("[llm].kv_cache_type erlaubt nur f16 oder q8_0")
if kv_cache_type == "q8_0" and accelerator_id != "cuda":
    raise SystemExit("[llm].kv_cache_type q8_0 ist derzeit nur für CUDA freigegeben")
backend_bind = final_cfg.get("asr", {}).get("backend_bind_address")
allowed_backend_binds = {"127.0.0.1", "0.0.0.0"}
if backend_bind not in allowed_backend_binds:
    raise SystemExit("[asr].backend_bind_address erlaubt nur 127.0.0.1 oder 0.0.0.0")
frame_threshold = final_cfg.get("asr", {}).get("frame_threshold")
if not isinstance(frame_threshold, int) or isinstance(frame_threshold, bool) or not 1 <= frame_threshold <= 1500:
    raise SystemExit("[asr].frame_threshold muss zwischen 1 und 1500 liegen")
text = set_section_key(text, "asr", "backend_host", "127.0.0.1")
text = set_section_key(text, "asr", "backend_type", asr_backend_type)
text = set_section_key(text, "asr", "model", "large-v3")
text = set_section_key(text, "asr", "model_path", asr_model_path)
text = set_section_key(text, "asr", "pcm_input", True)
text = set_section_key(text, "asr", "diarization", False)
text = set_section_key(text, "asr", "require_hardware_acceleration", True)
text = set_section_key(text, "asr", "allow_cpu_fallback", False)

tomllib.loads(text)
out_path.write_text(text.rstrip() + "\n", encoding="utf-8")
PY
    sudo install -m 0644 -o root -g "$ROOT_GROUP" "$tmp" "$CONFIG_FILE"
    rm -f "$tmp"
    log "Konfiguration aktiviert: $CONFIG_FILE"
}

validate_runtime_config() {
    [[ -r "$CONFIG_FILE" ]] || die "Konfiguration fehlt: $CONFIG_FILE"
    local expected_backend
    [[ "$PLATFORM" == "macos" ]] && expected_backend="mlx-whisper" || expected_backend="faster-whisper"
    EXPECTED_PLATFORM="$PLATFORM" EXPECTED_ACCELERATOR="$ACCELERATOR" EXPECTED_SERVICE_MANAGER="$SERVICE_MANAGER" EXPECTED_ASR_BACKEND="$expected_backend" \
    "$PYTHON" - "$CONFIG_FILE" <<'PY'
import os
import sys
import tomllib
from pathlib import Path

path = Path(sys.argv[1])
with path.open("rb") as f:
    cfg = tomllib.load(f)

if cfg.get("schema_version") != 3:
    raise SystemExit("schema_version muss 3 sein")
runtime = cfg.get("runtime", {})
expected = {
    "platform": os.environ["EXPECTED_PLATFORM"],
    "accelerator": os.environ["EXPECTED_ACCELERATOR"],
    "service_manager": os.environ["EXPECTED_SERVICE_MANAGER"],
}
for key, value in expected.items():
    if runtime.get(key) != value:
        raise SystemExit(f"[runtime].{key} muss {value!r} sein, ist aber {runtime.get(key)!r}")

role_sections = {"llm": "llm", "asr": "asr", "tts": "tts"}
roles = cfg.get("enabled_roles")
if not isinstance(roles, list) or not roles:
    raise SystemExit("enabled_roles muss eine nichtleere Liste sein")
if len(roles) != len(set(roles)):
    raise SystemExit("enabled_roles enthält Duplikate")
unknown = [role for role in roles if role not in role_sections]
if unknown:
    raise SystemExit(f"Unbekannte aktivierte Rollen: {unknown}")

bind = cfg.get("bind_address")
if not isinstance(bind, str) or not bind.strip():
    raise SystemExit("bind_address fehlt oder ist ungültig")

ports = {}
for role in roles:
    section = cfg.get(role_sections[role])
    if not isinstance(section, dict):
        raise SystemExit(f"Konfigurationsabschnitt fehlt: [{role_sections[role]}]")
    port = section.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SystemExit(f"Ungültiger Port für {role}: {port!r}")
    if port in ports:
        raise SystemExit(f"Portkollision: {role} und {ports[port]} verwenden {port}")
    ports[port] = role

if "llm" in roles:
    llm = cfg["llm"]
    if not Path(llm.get("model_path", "")).is_absolute():
        raise SystemExit("[llm].model_path muss absolut sein")
    slots = llm.get("slots")
    if not isinstance(slots, int) or isinstance(slots, bool) or not 1 <= slots <= 4:
        raise SystemExit("[llm].slots muss zwischen 1 und 4 liegen")
    if not isinstance(llm.get("context_size"), int) or llm["context_size"] < 4096:
        raise SystemExit("[llm].context_size muss mindestens 4096 sein")
    kv_cache_type = llm.get("kv_cache_type")
    if kv_cache_type not in {"f16", "q8_0"}:
        raise SystemExit("[llm].kv_cache_type erlaubt nur f16 oder q8_0")
    if kv_cache_type == "q8_0" and os.environ["EXPECTED_ACCELERATOR"] != "cuda":
        raise SystemExit("[llm].kv_cache_type q8_0 ist derzeit nur für CUDA freigegeben")
    if llm.get("continuous_batching") is not True or llm.get("streaming") is not True or llm.get("thinking") is not False:
        raise SystemExit("LLM-Batching/Streaming/Thinking-Konfiguration ist nicht wie vorgesehen")

if "asr" in roles:
    a = cfg["asr"]
    if a.get("protocol") != "kienzlefon-asr-v1" or a.get("backend") != "whisperlivekit":
        raise SystemExit("ASR-Protokoll/Backend ist nicht wie vorgesehen")
    if a.get("backend_host") != "127.0.0.1":
        raise SystemExit("Der interne WhisperLiveKit-Verbindungsweg muss IPv4-Loopback verwenden")
    backend_bind = a.get("backend_bind_address")
    if backend_bind not in {"127.0.0.1", "0.0.0.0"}:
        raise SystemExit("[asr].backend_bind_address ist ungültig")
    frame_threshold = a.get("frame_threshold")
    if not isinstance(frame_threshold, int) or isinstance(frame_threshold, bool) or not 1 <= frame_threshold <= 1500:
        raise SystemExit("[asr].frame_threshold muss zwischen 1 und 1500 liegen")
    bp = a.get("backend_port")
    if not isinstance(bp, int) or isinstance(bp, bool) or not 1 <= bp <= 65535:
        raise SystemExit("[asr].backend_port ist ungültig")
    if bp in ports:
        raise SystemExit(f"ASR-Backend-Port kollidiert mit öffentlichem Dienstport: {bp}")
    if a.get("backend_type") != os.environ["EXPECTED_ASR_BACKEND"]:
        raise SystemExit(f"Falsches ASR-Hardwarebackend: {a.get('backend_type')!r}")
    if a.get("model") != "large-v3":
        raise SystemExit("Whisper large-v3 ist erforderlich")
    if not Path(a.get("model_path", "")).is_absolute():
        raise SystemExit("[asr].model_path muss absolut sein")
    if a.get("pcm_input") is not True or a.get("diarization") is not False:
        raise SystemExit("ASR PCM/Diarisierungs-Konfiguration ist nicht wie vorgesehen")
    if a.get("require_hardware_acceleration") is not True or a.get("allow_cpu_fallback") is not False:
        raise SystemExit("ASR darf nicht still auf CPU zurückfallen")

if "tts" in roles:
    tts = cfg["tts"]
    for key in ("model_path", "model_config_path"):
        if not Path(tts.get(key, "")).is_absolute():
            raise SystemExit(f"[tts].{key} muss absolut sein")
    workers = tts.get("workers")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 32:
        raise SystemExit("[tts].workers muss zwischen 1 und 32 liegen")
    length_scale = tts.get("length_scale")
    if not isinstance(length_scale, (int, float)) or isinstance(length_scale, bool) or not 0.25 <= float(length_scale) <= 4.0:
        raise SystemExit("[tts].length_scale muss zwischen 0.25 und 4.0 liegen")
PY
}

read_enabled_roles() {
    [[ -r "$CONFIG_FILE" ]] || die "Konfiguration fehlt: $CONFIG_FILE"
    "$PYTHON" - "$CONFIG_FILE" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    cfg = tomllib.load(f)
for role in cfg.get("enabled_roles", []):
    print(role)
PY
}

config_get() {
    local dotted="$1"
    "$PYTHON" - "$CONFIG_FILE" "$dotted" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    value = tomllib.load(f)
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

contains_role() {
    local needle="$1" r
    shift
    for r in "$@"; do [[ "$r" == "$needle" ]] && return 0; done
    return 1
}

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    else sha256sum "$1" | awk '{print $1}'
    fi
}
md5_file() {
    if command -v md5 >/dev/null 2>&1; then md5 -q "$1"
    else md5sum "$1" | awk '{print $1}'
    fi
}

download_verified_sha256() {
    local url="$1" dest="$2" expected="$3" actual part
    if [[ -f "$dest" ]]; then
        actual="$(sha256_file "$dest")"
        if [[ "$actual" == "$expected" ]]; then
            log "Vorhandener Download geprüft: $(basename "$dest")"
            return
        fi
        warn "Prüfsumme falsch; verschiebe vorhandene Datei."
        mv "$dest" "${dest}.invalid.$(date +%s)"
    fi
    part="${dest}.part"
    log "Lade $(basename "$dest") ..."
    curl --fail --location --retry 5 --retry-all-errors --continue-at - --output "$part" "$url"
    actual="$(sha256_file "$part")"
    [[ "$actual" == "$expected" ]] || { rm -f "$part"; die "SHA256-Prüfung fehlgeschlagen für $(basename "$dest")."; }
    mv "$part" "$dest"
}

download_verified_md5() {
    local url="$1" dest="$2" expected="$3" actual part
    if [[ -f "$dest" ]]; then
        actual="$(md5_file "$dest")"
        if [[ "$actual" == "$expected" ]]; then
            log "Vorhandener Download geprüft: $(basename "$dest")"
            return
        fi
        mv "$dest" "${dest}.invalid.$(date +%s)"
    fi
    part="${dest}.part"
    log "Lade $(basename "$dest") ..."
    curl --fail --location --retry 5 --retry-all-errors --continue-at - --output "$part" "$url"
    actual="$(md5_file "$part")"
    [[ "$actual" == "$expected" ]] || { rm -f "$part"; die "MD5-Prüfung fehlgeschlagen für $(basename "$dest")."; }
    mv "$part" "$dest"
}

sync_git_repo() {
    local repo="$1" dir="$2" ref="$3"
    if [[ -d "$dir/.git" ]]; then
        [[ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ]] || die "Lokale Änderungen in $dir. Abbruch zum Schutz der Änderungen."
        git -C "$dir" remote set-url origin "$repo"
        git -C "$dir" fetch --tags --force origin
    elif [[ -e "$dir" ]]; then
        die "$dir existiert, ist aber kein Git-Repository."
    else
        git clone --filter=blob:none "$repo" "$dir"
        git -C "$dir" fetch --tags --force origin
    fi
    git -C "$dir" checkout --detach "$ref"
    log "Quelle fixiert: $(basename "$dir") @ $(git -C "$dir" rev-parse --short=12 HEAD)"
}

build_llama_cpp() {
    local src="${PREFIX}/src/llama.cpp" build="${PREFIX}/src/llama.cpp/build-kienzlefon" jobs
    sync_git_repo "$LLAMA_CPP_REPOSITORY" "$src" "$LLAMA_CPP_REF"
    if [[ "$PLATFORM" == "macos" ]]; then
        # Kienzlefon exposes llama-server only via its local/plain HTTP API.
        # Disable llama.cpp's optional OpenSSL/HTTPS support on macOS: this avoids
        # linking cpp-httplib against an accidental/mismatched OpenSSL installation
        # (notably Intel-vs-arm64 Homebrew) and keeps TLS out of the resident AI
        # service itself. Metal remains mandatory and is checked below.
        cmake -S "$src" -B "$build" -G Ninja \
            -DCMAKE_BUILD_TYPE=Release \
            -DGGML_METAL=ON \
            -DGGML_METAL_EMBED_LIBRARY=ON \
            -DGGML_NATIVE=ON \
            -DLLAMA_OPENSSL=OFF \
            -DLLAMA_BUILD_TESTS=OFF \
            -DLLAMA_BUILD_EXAMPLES=OFF \
            -DLLAMA_BUILD_TOOLS=ON
        jobs="$(sysctl -n hw.logicalcpu)"
    else
        command -v nvidia-smi >/dev/null 2>&1 || die "NVIDIA-Treiber/nvidia-smi fehlt; kein CPU-Fallback."
        nvidia-smi >/dev/null 2>&1 || die "NVIDIA-Treiber funktioniert nicht; nvidia-smi fehlgeschlagen."
        command -v nvcc >/dev/null 2>&1 || die "CUDA Toolkit/nvcc fehlt. Bitte vorhandenes CUDA-System zuerst vervollständigen; der Installer installiert keine GPU-Treiber."
        cmake -S "$src" -B "$build" -G Ninja \
            -DCMAKE_BUILD_TYPE=Release \
            -DGGML_CUDA=ON \
            -DGGML_NATIVE=ON \
            -DLLAMA_BUILD_TESTS=OFF \
            -DLLAMA_BUILD_EXAMPLES=OFF \
            -DLLAMA_BUILD_TOOLS=ON
        jobs="$(nproc)"
    fi
    cmake --build "$build" --target llama-server llama-cli -j "$jobs"
    # Die llama.cpp-Binaries bleiben im verwalteten Build-Verzeichnis. Symlinks
    # vermeiden, dass plattformspezifische Shared Libraries vom Binary getrennt
    # werden, während der stabile Kienzlefon-Pfad unter /opt erhalten bleibt.
    ln -sfn "$build/bin/llama-server" "$PREFIX/bin/llama-server"
    ln -sfn "$build/bin/llama-cli" "$PREFIX/bin/llama-cli"
    "$PREFIX/bin/llama-cli" --version >/dev/null 2>&1 || die "llama.cpp-Binary ist nach dem Build nicht lauffähig."
    if [[ "$PLATFORM" == "macos" ]]; then
        file -L "$PREFIX/bin/llama-server" | grep -q 'arm64' || die "llama-server wurde nicht als arm64 gebaut."
        grep -Eq '^GGML_METAL:BOOL=ON$' "$build/CMakeCache.txt" || die "llama.cpp wurde nicht mit Metal konfiguriert."
        grep -Eq '^LLAMA_OPENSSL:BOOL=OFF$' "$build/CMakeCache.txt" || die "llama.cpp OpenSSL/HTTPS ist unter macOS unerwartet aktiv."
    else
        file -L "$PREFIX/bin/llama-server" | grep -Eq 'x86-64|x86_64' || die "llama-server wurde nicht als x86_64 gebaut."
        grep -Eq '^GGML_CUDA:BOOL=ON$' "$build/CMakeCache.txt" || die "llama.cpp wurde nicht mit CUDA konfiguriert."
        "$PREFIX/bin/llama-cli" --list-devices 2>&1 | grep -qi 'CUDA' || die "llama.cpp erkennt nach dem Build kein CUDA-Gerät; kein CPU-Fallback."
    fi
}

install_asr_python() {
    local venv="${PREFIX}/python/asr-venv" wheel_dir="${DOWNLOAD_DIR}/whisperlivekit-wheels" wheel actual
    "$PYTHON" -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
    mkdir -p "$wheel_dir"
    rm -f "$wheel_dir"/whisperlivekit-*.whl
    "$venv/bin/python" -m pip download --no-deps --only-binary=:all: \
        --dest "$wheel_dir" "whisperlivekit==${WHISPERLIVEKIT_VERSION}"
    wheel="$(find "$wheel_dir" -maxdepth 1 -type f -name 'whisperlivekit-*.whl' -print -quit)"
    [[ -n "$wheel" ]] || die "WhisperLiveKit-Wheel nicht gefunden."
    actual="$(sha256_file "$wheel")"
    [[ "$actual" == "$WHISPERLIVEKIT_WHEEL_SHA256" ]] || die "WhisperLiveKit-Wheel-Prüfsumme stimmt nicht."

    if [[ "$PLATFORM" == "macos" ]]; then
        "$venv/bin/python" -m pip install "$wheel"
        "$venv/bin/python" -m pip install "mlx==${MLX_VERSION}" "mlx-whisper==${MLX_WHISPER_VERSION}"
        "$venv/bin/python" - <<PY
import importlib.metadata
assert importlib.metadata.version("whisperlivekit") == "${WHISPERLIVEKIT_VERSION}"
assert importlib.metadata.version("mlx") == "${MLX_VERSION}"
assert importlib.metadata.version("mlx-whisper") == "${MLX_WHISPER_VERSION}"
import mlx.core as mx
if not mx.metal.is_available():
    raise SystemExit("MLX meldet Metal als nicht verfügbar; CPU-Fallback wird nicht akzeptiert")
x = mx.arange(16, dtype=mx.float32)
y = (x * x).sum()
mx.eval(y)
print("MLX Metal verfügbar:", mx.metal.device_info())
PY
    else
        # CUDA-Torch zuerst installieren, damit WhisperLiveKit kein CPU-Torch
        # aus dem Standardindex vorinstalliert.
        "$venv/bin/python" -m pip install --index-url https://download.pytorch.org/whl/cu129 torch torchaudio
        "$venv/bin/python" -m pip install "$wheel"
        "$venv/bin/python" -m pip install --upgrade "faster-whisper==${FASTER_WHISPER_VERSION}"
        "$venv/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("PyTorch meldet CUDA als nicht verfügbar; CPU-Fallback wird nicht akzeptiert")
print("CUDA verfügbar:", torch.cuda.get_device_name(0), torch.version.cuda)
import ctranslate2
print("CTranslate2 CUDA compute types:", sorted(ctranslate2.get_supported_compute_types("cuda")))
PY
    fi
}

install_piper_python() {
    local venv="${PREFIX}/python/tts-venv" wheel_dir="${DOWNLOAD_DIR}/piper-wheels" wheel actual expected pattern
    "$PYTHON" -m venv "$venv"
    "$venv/bin/python" -m pip install --upgrade pip setuptools wheel
    mkdir -p "$wheel_dir"
    rm -f "$wheel_dir"/piper_tts-*.whl
    "$venv/bin/python" -m pip download --no-deps --only-binary=:all: \
        --dest "$wheel_dir" "piper-tts==${PIPER_TTS_VERSION}"
    if [[ "$PLATFORM" == "macos" ]]; then
        pattern='piper_tts-*-macosx_11_0_arm64.whl'
        expected="$PIPER_MACOS_ARM64_WHEEL_SHA256"
    else
        pattern='piper_tts-*-manylinux*_x86_64.whl'
        expected="$PIPER_LINUX_X86_64_WHEEL_SHA256"
    fi
    wheel="$(find "$wheel_dir" -maxdepth 1 -type f -name "$pattern" -print -quit)"
    [[ -n "$wheel" ]] || die "Passendes Piper-Wheel für $PLATFORM nicht gefunden."
    actual="$(sha256_file "$wheel")"
    [[ "$actual" == "$expected" ]] || die "Piper-Wheel-Prüfsumme stimmt nicht."
    "$venv/bin/python" -m pip install --upgrade "$wheel"
    "$venv/bin/python" - <<PY
import importlib.metadata
v = importlib.metadata.version("piper-tts")
assert v == "${PIPER_TTS_VERSION}", v
PY
}

download_role_models() {
    local role="$1" url model_dir
    case "$role" in
        llm)
            url="https://huggingface.co/${QWEN_GGUF_REPOSITORY}/resolve/${QWEN_GGUF_REVISION}/${QWEN_GGUF_FILENAME}?download=true"
            download_verified_sha256 "$url" "$PREFIX/models/$QWEN_GGUF_FILENAME" "$QWEN_GGUF_SHA256"
            ;;
        asr)
            if [[ "$PLATFORM" == "macos" ]]; then
                model_dir="$PREFIX/models/whisper-large-v3-mlx"
                mkdir -p "$model_dir"
                # SimulStreaming benötigt einen Decoder-Checkpoint; MLX liefert
                # zusätzlich den beschleunigten Encoder. Beides liegt gemeinsam in
                # einem expliziten, versionsgeprüften lokalen Modellverzeichnis.
                url="https://openaipublic.azureedge.net/main/whisper/models/${WHISPER_OPENAI_LARGE_V3_SHA256}/large-v3.pt"
                download_verified_sha256 "$url" "$model_dir/large-v3.pt" "$WHISPER_OPENAI_LARGE_V3_SHA256"
                url="https://huggingface.co/${WHISPER_MLX_REPOSITORY}/resolve/${WHISPER_MLX_REVISION}/${WHISPER_MLX_WEIGHTS_FILENAME}?download=true"
                download_verified_sha256 "$url" "$model_dir/${WHISPER_MLX_WEIGHTS_FILENAME}" "$WHISPER_MLX_WEIGHTS_SHA256"
                url="https://huggingface.co/${WHISPER_MLX_REPOSITORY}/resolve/${WHISPER_MLX_REVISION}/${WHISPER_MLX_CONFIG_FILENAME}?download=true"
                download_verified_sha256 "$url" "$model_dir/${WHISPER_MLX_CONFIG_FILENAME}" "$WHISPER_MLX_CONFIG_SHA256"
            else
                # SimulStreaming benötigt den nativen Whisper-Decoder; Faster-Whisper
                # stellt den CUDA-beschleunigten Encoder bereit. Das lokale Verzeichnis
                # enthält beide Darstellungen und verhindert spätere Modell-Downloads.
                model_dir="$PREFIX/models/whisper-large-v3-cuda"
                mkdir -p "$model_dir"
                url="https://openaipublic.azureedge.net/main/whisper/models/${WHISPER_OPENAI_LARGE_V3_SHA256}/large-v3.pt"
                download_verified_sha256 "$url" "$model_dir/large-v3.pt" "$WHISPER_OPENAI_LARGE_V3_SHA256"
                FW_OUTPUT_DIR="$model_dir" FW_REVISION="$WHISPER_CUDA_REVISION" \
                    "$PREFIX/python/asr-venv/bin/python" - <<'PYFW'
import os
from pathlib import Path
from faster_whisper.utils import download_model
root = Path(os.environ["FW_OUTPUT_DIR"])
path = Path(download_model("large-v3", output_dir=str(root), revision=os.environ["FW_REVISION"]))
model = path / "model.bin"
if not model.is_file():
    raise SystemExit(f"Faster-Whisper model.bin fehlt: {model}")
print(path)
PYFW
                [[ -f "$model_dir/model.bin" ]] || die "Faster-Whisper large-v3 model.bin wurde nicht gefunden."
                [[ "$(sha256_file "$model_dir/model.bin")" == "$WHISPER_CUDA_MODEL_SHA256" ]] || die "Faster-Whisper model.bin Prüfsumme stimmt nicht."
            fi
            ;;
        tts)
            url="https://huggingface.co/${PIPER_VOICE_REPOSITORY}/resolve/${PIPER_VOICE_REVISION}/${PIPER_VOICE_PATH}?download=true"
            download_verified_sha256 "$url" "$PREFIX/models/de_DE-thorsten-high.onnx" "$PIPER_VOICE_SHA256"
            url="https://huggingface.co/${PIPER_VOICE_REPOSITORY}/resolve/${PIPER_VOICE_REVISION}/${PIPER_VOICE_CONFIG_PATH}?download=true"
            download_verified_md5 "$url" "$PREFIX/models/de_DE-thorsten-high.onnx.json" "$PIPER_VOICE_CONFIG_MD5"
            ;;
    esac
}

write_service_runner() {
    cat >"$PREFIX/scripts/service_runner.py" <<'PY'
#!/usr/bin/env python3
import os
import sys
import tomllib
from pathlib import Path

CONFIG = Path("/etc/kienzlefon-ai/kienzlefon-ai-v2.toml")
PREFIX = Path("/opt/kienzlefon-ai-v2")


def fail(message: str) -> None:
    print(f"kienzlefon-ai: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("Rolle fehlt")
    role = sys.argv[1]
    with CONFIG.open("rb") as f:
        cfg = tomllib.load(f)
    public_roles = cfg.get("enabled_roles", [])
    if role != "asr-backend" and role not in public_roles:
        fail(f"Rolle ist nicht aktiviert: {role}")
    if role == "asr-backend" and "asr" not in public_roles:
        fail("ASR-Backend angefordert, aber Rolle asr ist nicht aktiviert")
    host = str(cfg["bind_address"])
    runtime = cfg.get("runtime", {})
    accelerator = runtime.get("accelerator")

    if role == "llm":
        c = cfg["llm"]
        if accelerator not in {"metal", "cuda"}:
            fail(f"Nicht unterstützter LLM-Beschleuniger: {accelerator}")
        cmd = [
            str(PREFIX / "bin/llama-server"),
            "--model", str(c["model_path"]),
            "--alias", str(c.get("model_alias", "qwen3.5-9b")),
            "--host", host,
            "--port", str(c["port"]),
            "--parallel", str(c["slots"]),
            "--ctx-size", str(c["context_size"]),
            "--n-gpu-layers", "999",
            "--reasoning", "off",
            "--reasoning-format", "deepseek",
            "--chat-template-kwargs", '{"enable_thinking":false}',
            "--no-mmproj",
            "--jinja",
            "--log-verbosity", "2",
        ]
        kv_cache_type = str(c.get("kv_cache_type", "f16"))
        if kv_cache_type == "q8_0":
            if accelerator != "cuda":
                fail("Q8_0-KV-Cache ist derzeit nur für CUDA freigegeben")
            cmd += [
                "--cache-type-k", "q8_0",
                "--cache-type-v", "q8_0",
                "--flash-attn", "on",
                "--fit", "off",
            ]
        elif kv_cache_type != "f16":
            fail(f"Nicht unterstützter LLM-KV-Cache: {kv_cache_type}")
        if bool(c.get("continuous_batching", True)):
            cmd.append("--cont-batching")
    elif role == "asr-backend":
        c = cfg["asr"]
        backend = str(c.get("backend_type", ""))
        expected = "mlx-whisper" if accelerator == "metal" else "faster-whisper" if accelerator == "cuda" else ""
        if backend != expected or c.get("allow_cpu_fallback") is not False:
            fail(f"ASR-Konfiguration passt nicht zum Hardwareprofil {accelerator}: {backend}")
        cmd = [
            str(PREFIX / "python/asr-venv/bin/wlk"),
            "--backend", backend,
            "--backend-policy", str(c.get("backend_policy", "simulstreaming")),
            "--language", str(c.get("language", "de")),
            "--host", str(c.get("backend_bind_address", "127.0.0.1")),
            "--port", str(c["backend_port"]),
            "--frame-threshold", str(c.get("frame_threshold", 25)),
            "--pcm-input",
        ]

        # WLK-Defaults nicht explizit übergeben.
        # Nur echte Testabweichungen auf die Kommandozeile setzen.
        beams = int(c.get("beams", 1))
        if beams != 1:
            cmd += ["--beams", str(beams)]

        decoder = str(c.get("decoder", "auto"))
        if decoder != "auto":
            cmd += ["--decoder", decoder]

        if bool(c.get("never_fire", False)):
            cmd.append("--never-fire")

        model_path = str(c.get("model_path", ""))
        # Das plattformspezifische Modellverzeichnis enthält jeweils den nativen
        # Decoder und den beschleunigten Encoder (MLX bzw. Faster-Whisper).
        cmd += ["--model-path", model_path]
        # Absichtlich KEIN --diarization.
    elif role == "asr":
        c = cfg["asr"]
        cmd = [
            str(PREFIX / "python/asr-venv/bin/python"),
            str(PREFIX / "scripts/asr_gateway.py"),
            "--host", host,
            "--port", str(c["port"]),
            "--backend-host", str(c["backend_host"]),
            "--backend-port", str(c["backend_port"]),
            "--language", str(c.get("language", "de")),
        ]
    elif role == "tts":
        c = cfg["tts"]
        cmd = [
            str(PREFIX / "python/tts-venv/bin/python"),
            str(PREFIX / "scripts/piper_service.py"),
            "--host", host,
            "--port", str(c["port"]),
            "--model", str(c["model_path"]),
            "--config", str(c["model_config_path"]),
            "--workers", str(c["workers"]),
            "--length-scale", str(c["length_scale"]),
        ]
    else:
        fail(f"Unbekannte Rolle: {role}")

    if not Path(cmd[0]).exists():
        fail(f"Programm fehlt: {cmd[0]}")
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
PY
    chmod 0755 "$PREFIX/scripts/service_runner.py"
}

write_runtime_scripts() {
    write_service_runner

    cat >"$PREFIX/scripts/asr_gateway.py" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from websockets.asyncio.client import connect
import uvicorn

PROTOCOL = "kienzlefon-asr-v1"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
settings: dict[str, Any] = {}


def backend_health_sync() -> bool:
    url = f"http://{settings['backend_host']}:{settings['backend_port']}/health"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


@app.get("/health")
async def health() -> JSONResponse:
    ok = await asyncio.to_thread(backend_health_sync)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "backend_unavailable",
            "protocol": PROTOCOL,
            "backend": "whisperlivekit",
            "model": "large-v3",
            "streaming": True,
            "partial": True,
            "confirmed": True,
            "diarization": False,
        },
    )


def clean_line(line: Any) -> dict[str, Any] | None:
    if not isinstance(line, dict) or line.get("speaker") == -2:
        return None
    text = line.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return {"type": "confirmed", "text": text.strip(), "start": line.get("start"), "end": line.get("end")}


@app.websocket("/v1/asr/stream")
async def asr_stream(client: WebSocket) -> None:
    await client.accept()
    query = urlencode({"language": settings["language"], "mode": "full"})
    backend_url = f"ws://{settings['backend_host']}:{settings['backend_port']}/asr?{query}"
    try:
        async with connect(backend_url, max_size=None, ping_interval=20, ping_timeout=20) as backend:
            first = json.loads(await asyncio.wait_for(backend.recv(), timeout=15.0))
            if first.get("type") != "config" or first.get("useAudioWorklet") is not True:
                raise RuntimeError("WhisperLiveKit erwartet nicht PCM s16le/16kHz/mono")
            await client.send_json({
                "type": "ready",
                "protocol": PROTOCOL,
                "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
            })

            async def client_to_backend() -> None:
                while True:
                    message = await client.receive()
                    if message["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    data = message.get("bytes")
                    if data is None:
                        # Die abstrakte Schnittstelle akzeptiert bewusst nur Binär-PCM.
                        continue
                    await backend.send(data)
                    if data == b"":
                        return

            async def backend_to_client() -> None:
                last_partial = None
                emitted_confirmed: set[tuple[Any, ...]] = set()
                while True:
                    raw = await backend.recv()
                    msg = json.loads(raw)
                    if msg.get("error"):
                        await client.send_json({"type": "error", "code": "backend_error"})
                        return
                    mtype = msg.get("type")
                    # Wir verwenden intern den stabileren Full-Modus. Snapshot/Diff wird
                    # dennoch toleriert, damit die Abstraktionsschicht backendrobust bleibt.
                    if mtype == "diff":
                        lines = msg.get("new_lines", [])
                    else:
                        lines = msg.get("lines", [])
                    for line in lines:
                        event = clean_line(line)
                        if event:
                            key = (event.get("start"), event.get("end"), event.get("text"))
                            if key not in emitted_confirmed:
                                emitted_confirmed.add(key)
                                await client.send_json(event)
                    partial = msg.get("buffer_transcription", "")
                    if isinstance(partial, str):
                        partial = partial.strip()
                        if partial != last_partial:
                            await client.send_json({"type": "partial", "text": partial})
                            last_partial = partial
                    if mtype == "ready_to_stop":
                        await client.send_json({"type": "end"})
                        return

            sender = asyncio.create_task(client_to_backend())
            receiver = asyncio.create_task(backend_to_client())
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await client.send_json({"type": "error", "code": "stream_failed"})
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--backend-host", required=True)
    parser.add_argument("--backend-port", required=True, type=int)
    parser.add_argument("--language", default="de")
    args = parser.parse_args()
    settings.update(vars(args))
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
PY

    cat >"$PREFIX/scripts/piper_service.py" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import queue
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from piper import PiperVoice, SynthesisConfig


class VoicePool:
    def __init__(self, model: str, config: str, workers: int) -> None:
        self.total = workers
        self.pool: queue.Queue[PiperVoice] = queue.Queue(maxsize=workers)
        for _ in range(workers):
            self.pool.put(PiperVoice.load(model, config_path=config))

    def acquire(self, timeout: float = 120.0) -> PiperVoice:
        return self.pool.get(timeout=timeout)

    def release(self, voice: PiperVoice) -> None:
        self.pool.put(voice)

    @property
    def available(self) -> int:
        return self.pool.qsize()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], pool: VoicePool, default_length_scale: float) -> None:
        super().__init__(address, handler)
        self.voice_pool = pool
        self.default_length_scale = default_length_scale


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Absichtlich keine Texte, Request-Bodies oder Header protokollieren.
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {
                "status": "ok",
                "model_loaded": True,
                "workers": self.server.voice_pool.total,
                "workers_available": self.server.voice_pool.available,
            })
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/audio/speech":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid_content_length")
            payload = json.loads(self.rfile.read(length))
            text = payload.get("input", payload.get("text", ""))
            if not isinstance(text, str) or not text.strip():
                raise ValueError("input must be a non-empty string")
            response_format = str(payload.get("response_format", "wav")).lower()
            if response_format not in {"wav", "pcm"}:
                raise ValueError("response_format must be wav or pcm")
            raw_scale = payload.get("length_scale", self.server.default_length_scale)
            length_scale = float(raw_scale)
            if not 0.25 <= length_scale <= 4.0:
                raise ValueError("length_scale out of range")
            syn_config = SynthesisConfig(length_scale=length_scale)

            voice = self.server.voice_pool.acquire()
            try:
                if response_format == "wav":
                    buffer = io.BytesIO()
                    with wave.open(buffer, "wb") as wav_file:
                        voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                    audio = buffer.getvalue()
                    media_type = "audio/wav"
                else:
                    chunks = [chunk.audio_int16_bytes for chunk in voice.synthesize(text, syn_config=syn_config)]
                    audio = b"".join(chunks)
                    media_type = "application/octet-stream"
            finally:
                self.server.voice_pool.release(voice)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
        except queue.Empty:
            self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "all_workers_busy"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            # Keine Texte oder internen Daten in der normalen HTTP-Antwort protokollieren.
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "synthesis_failed"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--workers", required=True, type=int)
    parser.add_argument("--length-scale", required=True, type=float)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 32:
        raise SystemExit("workers must be between 1 and 32")
    pool = VoicePool(args.model, args.config, args.workers)
    server = Server((args.host, args.port), Handler, pool, args.length_scale)
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
PY

    chmod 0755 "$PREFIX/scripts/asr_gateway.py" "$PREFIX/scripts/piper_service.py"
}

role_label() {
    case "$1" in
        llm) echo "de.kienzlefon.ai.llm" ;;
        asr) echo "de.kienzlefon.ai.asr" ;;
        asr-backend) echo "de.kienzlefon.ai.asr-backend" ;;
        tts) echo "de.kienzlefon.ai.tts" ;;
        *) return 1 ;;
    esac
}

role_plist() { echo "$PLIST_DIR/$(role_label "$1").plist"; }
role_systemd_name() { echo "kienzlefon-ai-$1.service"; }
role_systemd_unit() { echo "$SYSTEMD_DIR/$(role_systemd_name "$1")"; }
role_log_base() { echo "$LOG_DIR/$1"; }

write_service_definition() {
    local role="$1" logbase tmp
    logbase="$(role_log_base "$role")"
    tmp="$(mktemp)"
    if [[ "$SERVICE_MANAGER" == "launchd" ]]; then
        local label plist
        label="$(role_label "$role")"
        plist="$(role_plist "$role")"
        cat >"$tmp" <<EOF2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${PREFIX}/scripts/service_runner.py</string>
    <string>${role}</string>
  </array>
  <key>UserName</key><string>${INSTALL_USER}</string>
  <key>GroupName</key><string>${INSTALL_GROUP}</string>
  <key>WorkingDirectory</key><string>${PREFIX}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${BREW_PREFIX}/bin:${BREW_PREFIX}/sbin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>StandardOutPath</key><string>${logbase}.out.log</string>
  <key>StandardErrorPath</key><string>${logbase}.err.log</string>
</dict>
</plist>
EOF2
        plutil -lint "$tmp" >/dev/null
        sudo install -m 0644 -o root -g "$ROOT_GROUP" "$tmp" "$plist"
    else
        local unit after="network.target" requires=""
        unit="$(role_systemd_unit "$role")"
        if [[ "$role" == "asr" ]]; then
            after="network.target $(role_systemd_name asr-backend)"
            requires="Requires=$(role_systemd_name asr-backend)"
        fi
        cat >"$tmp" <<EOF2
[Unit]
Description=Kienzlefon AI ${role}
After=${after}
${requires}

[Service]
Type=simple
User=${INSTALL_USER}
Group=${INSTALL_GROUP}
WorkingDirectory=${PREFIX}
ExecStart=${PYTHON} ${PREFIX}/scripts/service_runner.py ${role}
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin
StandardOutput=append:${logbase}.out.log
StandardError=append:${logbase}.err.log

[Install]
WantedBy=multi-user.target
EOF2
        sudo install -m 0644 -o root -g root "$tmp" "$unit"
        sudo systemctl daemon-reload
        sudo systemctl enable "$(role_systemd_name "$role")" >/dev/null
    fi
    rm -f "$tmp"
}

wait_launchd_unloaded() {
    local label="$1" i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if ! sudo launchctl print "system/$label" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

bootstrap_launchd_service() {
    local label="$1" plist="$2" rc=0 i
    # Auf aktuellen macOS-Versionen kann enable vor bootstrap erforderlich sein.
    sudo launchctl enable "system/$label" >/dev/null 2>&1 || true

    for i in 1 2 3 4 5; do
        if sudo launchctl bootstrap system "$plist"; then
            return 0
        else
            rc=$?
        fi

        # Darwin EALREADY=37: launchd baut ggf. gerade noch die vorherige
        # Instanz ab oder hat die neue Definition zwischenzeitlich selbst geladen.
        if [[ "$rc" -eq 37 ]]; then
            if sudo launchctl print "system/$label" >/dev/null 2>&1; then
                log "LaunchDaemon $label ist bereits registriert; verwende vorhandene Registrierung."
                return 0
            fi
            log "LaunchDaemon $label wird noch umgeladen; erneuter bootstrap-Versuch ($i/5) ..."
            sleep 1
            continue
        fi

        warn "launchctl bootstrap für $label fehlgeschlagen (Exit $rc)."
        sudo launchctl error "$rc" 2>/dev/null >&2 || true
        return "$rc"
    done

    die "LaunchDaemon $label ließ sich nach mehreren Versuchen nicht registrieren."
}

start_one_service() {
    local role="$1"
    if [[ "$SERVICE_MANAGER" == "launchd" ]]; then
        local label plist
        label="$(role_label "$role")"; plist="$(role_plist "$role")"
        [[ -f "$plist" ]] || die "LaunchDaemon fehlt: $plist"

        if ! sudo launchctl print "system/$label" >/dev/null 2>&1; then
            bootstrap_launchd_service "$label" "$plist"
        fi
        sudo launchctl enable "system/$label" >/dev/null 2>&1 || true
        # Ohne -k: bootstrap + RunAtLoad startet bereits; kickstart stellt nur
        # sicher, dass ein registrierter, aber nicht laufender Dienst startet.
        local rc=0
        if sudo launchctl kickstart "system/$label"; then
            :
        else
            rc=$?
            if [[ "$rc" -eq 37 ]] && sudo launchctl print "system/$label" >/dev/null 2>&1; then
                log "LaunchDaemon $label wird bereits gestartet; fahre fort."
            else
                warn "launchctl kickstart für $label fehlgeschlagen (Exit $rc)."
                sudo launchctl error "$rc" 2>/dev/null >&2 || true
                return "$rc"
            fi
        fi
    else
        local unit
        unit="$(role_systemd_name "$role")"
        [[ -f "$(role_systemd_unit "$role")" ]] || die "systemd-Unit fehlt: $(role_systemd_unit "$role")"
        sudo systemctl start "$unit"
    fi
}

stop_one_service() {
    local role="$1"
    if [[ "$SERVICE_MANAGER" == "launchd" ]]; then
        local label plist rc=0
        label="$(role_label "$role")"
        plist="$(role_plist "$role")"

        # Wichtig bei KeepAlive=true: ein bloßes SIGTERM/kill führt sonst sofort
        # zum Relaunch. disable macht den Stop außerdem reboot-fest; start_one_service
        # hebt diesen Zustand mit enable wieder auf.
        sudo launchctl disable "system/$label" >/dev/null 2>&1 || true

        if sudo launchctl print "system/$label" >/dev/null 2>&1; then
            # Bevorzugt über die konkrete plist aus dem system-Domain entfernen.
            if [[ -f "$plist" ]] && sudo launchctl bootout system "$plist"; then
                :
            else
                rc=$?
                # Zweiter Versuch über das Service-Target.
                if sudo launchctl print "system/$label" >/dev/null 2>&1; then
                    if sudo launchctl bootout "system/$label"; then
                        :
                    else
                        rc=$?
                    fi
                fi
            fi

            # Fallback für störrische, bereits geladene Jobs. remove ist legacy,
            # entfernt als root aber aus dem system-Domain. Nur verwenden, wenn
            # der moderne bootout-Weg den Job tatsächlich nicht entfernt hat.
            if sudo launchctl print "system/$label" >/dev/null 2>&1; then
                warn "LaunchDaemon $label ist nach bootout noch registriert; versuche launchctl remove."
                sudo launchctl remove "$label" >/dev/null 2>&1 || true
            fi

            if ! wait_launchd_unloaded "$label"; then
                warn "LaunchDaemon $label ist 15 Sekunden nach Stop noch registriert."
                sudo launchctl print "system/$label" 2>&1 | head -80 >&2 || true
                die "LaunchDaemon $label konnte nicht gestoppt werden."
            fi
        fi
    else
        sudo systemctl stop "$(role_systemd_name "$role")" 2>/dev/null || true
    fi
}

start_role() {
    local role="$1"
    if [[ "$role" == "asr" ]]; then
        start_one_service asr-backend
        wait_role_ready asr-backend
        start_one_service asr
    else
        start_one_service "$role"
    fi
}

stop_role() {
    local role="$1"
    if [[ "$role" == "asr" ]]; then
        stop_one_service asr
        stop_one_service asr-backend
    else
        stop_one_service "$role"
    fi
}

restart_role() {
    stop_role "$1"
    start_role "$1"
}

role_port_key() {
    case "$1" in
        llm) echo "llm.port" ;;
        asr) echo "asr.port" ;;
        asr-backend) echo "asr.backend_port" ;;
        tts) echo "tts.port" ;;
    esac
}

http_host_from_config() {
    local host
    host="$(config_get bind_address)"
    [[ "$host" == "0.0.0.0" ]] && host="127.0.0.1"
    [[ "$host" == "::" ]] && host="::1"
    if [[ "$host" == *:* ]]; then
        printf '[%s]\n' "$host"
    else
        printf '%s\n' "$host"
    fi
}

wait_http() {
    local url="$1" attempts="${2:-180}" i
    for ((i=1; i<=attempts; i++)); do
        if curl --silent --show-error --fail --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    return 1
}

wait_role_ready() {
    local role="$1" host port url
    if [[ "$role" == "asr-backend" ]]; then
        host="$(config_get asr.backend_host)"
    else
        host="$(http_host_from_config)"
    fi
    port="$(config_get "$(role_port_key "$role")")"
    case "$role" in
        llm|tts|asr|asr-backend) url="http://${host}:${port}/health" ;;
        *) die "Kein Healthcheck für $role definiert" ;;
    esac
    wait_http "$url" 300 || die "$role wurde nicht rechtzeitig bereit. Logs: $(role_log_base "$role").err.log"
}

status_one_service() {
    local role="$1" port pid
    port="$(config_get "$(role_port_key "$role")")"
    if [[ "$SERVICE_MANAGER" == "launchd" ]]; then
        local label
        label="$(role_label "$role")"
        if sudo launchctl print "system/$label" >/dev/null 2>&1; then
            pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
            printf '%-20s geladen, Port %-5s, PID %s\n' "$role" "$port" "${pid:-noch nicht lauschend}"
        else
            printf '%-20s nicht geladen\n' "$role"
        fi
    else
        local unit state
        unit="$(role_systemd_name "$role")"
        state="$(systemctl is-active "$unit" 2>/dev/null || true)"
        pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
        printf '%-20s %-10s Port %-5s, PID %s\n' "$role" "${state:-unbekannt}" "$port" "${pid:-noch nicht lauschend}"
    fi
}

status_role() {
    if [[ "$1" == "asr" ]]; then
        status_one_service asr-backend
        status_one_service asr
    else
        status_one_service "$1"
    fi
}

make_test_audio() {
    local target="$1" temp
    if [[ "$PLATFORM" == "macos" ]]; then
        temp="${target%.wav}.aiff"
        if ! say -v Anna "Dies ist ein deutscher Streaming Test für Kienzlefon. Heute prüfen wir fortlaufende Transkription mit mehreren gesprochenen Wörtern und einem vollständigen Satz." -o "$temp" 2>/dev/null; then
            say "Dies ist ein deutscher Streaming Test für Kienzlefon. Heute prüfen wir fortlaufende Transkription mit mehreren gesprochenen Wörtern und einem vollständigen Satz." -o "$temp"
        fi
    else
        temp="${target%.wav}.source.wav"
        espeak-ng -v de -s 145 -w "$temp" "Dies ist ein deutscher Streaming Test für Kienzlefon. Heute prüfen wir fortlaufende Transkription mit mehreren gesprochenen Wörtern und einem vollständigen Satz."
    fi
    ffmpeg -hide_banner -loglevel error -y -i "$temp" -ar 16000 -ac 1 -c:a pcm_s16le "$target"
    rm -f "$temp"
}

assert_llm_acceleration() {
    local base logs=()
    base="$(role_log_base llm)"
    logs=("${base}.out.log" "${base}.err.log")
    if [[ "$ACCELERATOR" == "metal" ]]; then
        local devices port pid command_line build_cache
        devices="$("$PREFIX/bin/llama-cli" --list-devices 2>&1 || true)"
        if ! grep -Eqi 'Metal|MTL|Apple' <<<"$devices"; then
            log "Metal-Diagnose: llama.cpp Geräte:"
            printf '%s\n' "$devices" >&2
            die "llama.cpp sieht kein Metal-Gerät; CPU-only-Fallback wird nicht akzeptiert."
        fi

        build_cache="$PREFIX/src/llama.cpp/build-kienzlefon/CMakeCache.txt"
        grep -Eq '^GGML_METAL:BOOL=ON$' "$build_cache" || \
            die "Der laufende llama.cpp-Build ist nicht mit GGML_METAL=ON konfiguriert."

        port="$(config_get llm.port)"
        pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true)"
        [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || \
            die "Kein laufender llama-server-PID auf LLM-Port $port ermittelbar."
        command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        [[ "$command_line" == *"llama-server"* ]] || \
            die "Der Prozess auf LLM-Port $port ist nicht als llama-server erkennbar: $command_line"
        if [[ "$command_line" != *"--n-gpu-layers 999"* && "$command_line" != *"--n-gpu-layers all"* ]]; then
            log "Metal-Diagnose: laufende llama-server-Kommandozeile:"
            printf '%s\n' "$command_line" >&2
            die "Der laufende llama-server erzwingt kein vollständiges GPU-Offloading."
        fi
        if [[ "$command_line" == *"--n-gpu-layers 0"* || "$command_line" == *"--device none"* ]]; then
            die "Der laufende llama-server deaktiviert GPU-Offloading ausdrücklich; CPU-only-Fallback wird nicht akzeptiert."
        fi

        # llama.cpp dokumentiert Metal auf macOS als GPU-Backend; mit einem
        # sichtbaren Metal-Gerät und --n-gpu-layers 999/all wird maximal auf die
        # GPU ausgelagert. Startup-Logtexte ändern sich zwischen Releases und
        # sind daher nur ein zusätzlicher Diagnosehinweis, kein harter Test.
        log "Metal-Offload-Konfiguration ok: llama-server PID $pid, Metal-Gerät erkannt, GPU-Layer=999."
        if ! grep -Eiq 'metal|ggml_metal|gpu.*apple|apple.*gpu|offload.*gpu|offloaded.*gpu|offloading.*layers|layers.*gpu' "${logs[@]}" 2>/dev/null; then
            log "Hinweis: Kein Metal-Schlüsselwort im LLM-Log; der Nachweis erfolgte über Metal-Geräteerkennung, den Metal-Build und die laufende GPU-Offload-Konfiguration."
        fi
    else
        local unit pid smi_pids smi_detail
        "$PREFIX/bin/llama-cli" --list-devices 2>&1 | grep -qi 'CUDA' || \
            die "llama.cpp sieht kein CUDA-Gerät; CPU-only-Fallback wird nicht akzeptiert."

        unit="$(role_systemd_name llm)"
        pid="$(sudo systemctl show -p MainPID --value "$unit" 2>/dev/null || true)"
        [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || \
            die "Kein laufender llama-server-MainPID für $unit ermittelbar."

        smi_pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits 2>/dev/null || true)"
        if ! awk -v expected="$pid" '$1 == expected { found=1 } END { exit(found ? 0 : 1) }' <<<"$smi_pids"; then
            log "CUDA-Diagnose: systemd MainPID für llama-server: $pid"
            log "CUDA-Diagnose: llama.cpp Geräte:"
            "$PREFIX/bin/llama-cli" --list-devices >&2 2>&1 || true
            log "CUDA-Diagnose: NVIDIA Compute-Prozesse:"
            smi_detail="$(nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader 2>/dev/null || true)"
            if [[ -n "$smi_detail" ]]; then
                printf '%s\n' "$smi_detail" >&2
            else
                nvidia-smi >&2 2>&1 || true
            fi
            log "CUDA-Diagnose: letzte LLM-Logzeilen:"
            tail -n 80 "${logs[@]}" >&2 2>/dev/null || true
            die "llama-server PID $pid erscheint nicht als NVIDIA-CUDA-Compute-Prozess. CPU-only-Fallback wird nicht akzeptiert."
        fi

        log "CUDA-Laufzeitnachweis ok: llama-server PID $pid läuft als NVIDIA-Compute-Prozess."
        # Startup-Logtexte von llama.cpp ändern sich zwischen Versionen. Sie sind
        # deshalb nur noch zusätzlicher Hinweis und kein harter CUDA-Nachweis.
        if ! grep -Eiq 'cuda|ggml_cuda|nvidia|offload.*gpu|offloaded.*gpu' "${logs[@]}" 2>/dev/null; then
            log "Hinweis: Kein CUDA-Schlüsselwort im LLM-Log; der CUDA-Nachweis erfolgte direkt über den laufenden NVIDIA-Compute-Prozess."
        fi
    fi
}

test_llm() {
    local host port base tmpdir canary response content i pids=()
    host="$(http_host_from_config)"
    port="$(config_get llm.port)"; base="http://${host}:${port}"
    wait_http "$base/health" 300 || die "LLM-Healthcheck fehlgeschlagen."
    canary="KIENZLEFON_LOG_CANARY_92741"
    response="$(curl --silent --show-error --fail "$base/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        --data "{\"model\":\"qwen3.5-9b\",\"messages\":[{\"role\":\"user\",\"content\":\"Antworte nur mit: Dienst bereit. ${canary}\"}],\"max_tokens\":40,\"stream\":false}")"
    content="$(jq -r '.choices[0].message.content // empty' <<<"$response")"
    [[ -n "$content" ]] || die "LLM lieferte keine Antwort."
    if grep -Eqi '<think>|</think>' <<<"$content"; then
        printf '[kienzlefon-ai] LLM-Testantwort: %s\n' "$content" >&2
        die "Thinking-Tags stehen im normalen Antwortinhalt."
    fi
    if [[ "$(jq -r '.choices[0].message.reasoning_content // empty' <<<"$response")" != "" ]]; then
        printf '[kienzlefon-ai] LLM-Testantwort: %s\n' "$response" >&2
        die "reasoning_content ist trotz global deaktiviertem Thinking nicht leer."
    fi

    # Zusätzlich die von Qwen dokumentierte API-seitige Non-Thinking-Steuerung prüfen.
    response="$(curl --silent --show-error --fail "$base/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        --data "{\"model\":\"qwen3.5-9b\",\"messages\":[{\"role\":\"user\",\"content\":\"Antworte nur mit: API bereit.\"}],\"max_tokens\":40,\"stream\":false,\"reasoning_effort\":\"none\",\"chat_template_kwargs\":{\"enable_thinking\":false}}")"
    content="$(jq -r '.choices[0].message.content // empty' <<<"$response")"
    [[ -n "$content" ]] || die "LLM lieferte beim expliziten Non-Thinking-Test keine Antwort."
    if grep -Eqi '<think>|</think>' <<<"$content" || [[ "$(jq -r '.choices[0].message.reasoning_content // empty' <<<"$response")" != "" ]]; then
        printf '[kienzlefon-ai] LLM-Testantwort: %s\n' "$response" >&2
        die "Expliziter Non-Thinking-Test fehlgeschlagen."
    fi

    tmpdir="$(mktemp -d)"
    for i in 1 2 3 4; do
        curl --silent --show-error --fail "$base/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            --data "{\"model\":\"qwen3.5-9b\",\"messages\":[{\"role\":\"user\",\"content\":\"Nenne die Zahl ${i} auf Deutsch.\"}],\"max_tokens\":20,\"stream\":true}" \
            >"$tmpdir/$i.out" &
        pids+=("$!")
    done
    for i in "${pids[@]}"; do wait "$i"; done
    for i in 1 2 3 4; do [[ -s "$tmpdir/$i.out" ]] || die "Parallele LLM-Anfrage $i fehlgeschlagen."; done
    rm -rf "$tmpdir"
    assert_llm_acceleration
}

assert_asr_acceleration() {
    if [[ "$ACCELERATOR" == "metal" ]]; then
        "$PREFIX/python/asr-venv/bin/python" - <<'PY'
import mlx.core as mx
if not mx.metal.is_available():
    raise SystemExit("MLX Metal ist nicht verfügbar")
x = mx.arange(32, dtype=mx.float32)
y = (x * x).sum()
mx.eval(y)
print("MLX/Metal-Test ok")
PY
    else
        "$PREFIX/python/asr-venv/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("PyTorch CUDA ist nicht verfügbar")
import ctranslate2
cts = ctranslate2.get_supported_compute_types("cuda")
if not cts:
    raise SystemExit("CTranslate2 meldet keine CUDA-Compute-Types")
print("CUDA-ASR-Test ok:", torch.cuda.get_device_name(0), sorted(cts))
PY
    fi
}

make_test_pcm() {
    local wav="$1" pcm="$2"
    ffmpeg -hide_banner -loglevel error -y -i "$wav" -f s16le -acodec pcm_s16le -ar 16000 -ac 1 "$pcm"
}

stream_test_client() {
    local pcm="$1" output="$2" host port
    host="$(config_get bind_address)"
    [[ "$host" == "0.0.0.0" ]] && host="127.0.0.1"
    [[ "$host" == "::" ]] && host="::1"
    port="$(config_get asr.port)"
    ASR_HOST="$host" ASR_PORT="$port" PCM_FILE="$pcm" OUTPUT_FILE="$output" \
    "$PREFIX/python/asr-venv/bin/python" - <<'PY'
import asyncio
import json
import os
from pathlib import Path
from websockets.asyncio.client import connect

async def main():
    host = os.environ["ASR_HOST"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    uri = f"ws://{host}:{os.environ['ASR_PORT']}/v1/asr/stream"
    data = Path(os.environ["PCM_FILE"]).read_bytes()
    events = []
    async with connect(uri, max_size=None) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), 20))
        events.append(ready)
        if ready.get("type") != "ready" or ready.get("protocol") != "kienzlefon-asr-v1":
            raise SystemExit("Ungültiges ASR-ready-Ereignis")
        # 0,5 s PCM = 16000 Bytes bei 16 kHz, mono, s16le.
        for off in range(0, len(data), 16000):
            await ws.send(data[off:off+16000])
            await asyncio.sleep(0.5)
        await ws.send(b"")
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), 120))
            events.append(event)
            if event.get("type") in {"end", "error"}:
                break
    Path(os.environ["OUTPUT_FILE"]).write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n")
    if any(e.get("type") == "error" for e in events):
        raise SystemExit("ASR-Stream meldete einen Fehler")
    # WhisperLiveKit dokumentiert buffer_transcription als flüchtigen, noch nicht
    # committed Text. Dieser Buffer darf bei kurzen/eindeutigen Abschnitten leer
    # bleiben, wenn Text direkt als committed line ausgegeben wird. Deshalb ist
    # ein Partial-Ereignis Pflicht, nicht jedoch ein nichtleerer Partial-Text.
    partial_events = [e for e in events if e.get("type") == "partial"]
    confirmed = [e for e in events if e.get("type") == "confirmed" and e.get("text")]
    if not partial_events:
        raise SystemExit("Kein partial-Ereignis empfangen")
    if not confirmed:
        raise SystemExit("Kein nichtleeres confirmed-Transkript empfangen")
    if not any(e.get("type") == "end" for e in events):
        raise SystemExit("Kein Stream-Ende empfangen")
    text = " ".join(str(e.get("text", "")).strip() for e in confirmed).strip()
    nonempty_partial = any(str(e.get("text", "")).strip() for e in partial_events)
    print(f"ASR-Streaming-Test ok: confirmed={text!r}; nonempty_partial={nonempty_partial}")

asyncio.run(main())
PY
}


test_asr() {
    local audio="$1" tmpdir pcm events backend_host backend_port gateway_host gateway_port backend_pid gateway_pid health
    assert_asr_acceleration
    backend_host="$(config_get asr.backend_host)"
    backend_port="$(config_get asr.backend_port)"
    gateway_host="$(http_host_from_config)"
    gateway_port="$(config_get asr.port)"
    wait_http "http://${backend_host}:${backend_port}/health" 300 || die "WhisperLiveKit-Healthcheck fehlgeschlagen."
    health="$(curl --silent --show-error --fail "http://${gateway_host}:${gateway_port}/health")"
    [[ "$(jq -r '.status' <<<"$health")" == "ok" ]] || die "ASR-Gateway meldet nicht ok."
    [[ "$(jq -r '.diarization' <<<"$health")" == "false" ]] || die "ASR-Gateway meldet Diarisierung aktiv."

    backend_pid="$(lsof -nP -iTCP:"$backend_port" -sTCP:LISTEN -t | head -n1 || true)"
    gateway_pid="$(lsof -nP -iTCP:"$gateway_port" -sTCP:LISTEN -t | head -n1 || true)"
    [[ -n "$backend_pid" && -n "$gateway_pid" && "$backend_pid" != "$gateway_pid" ]] || die "ASR-Backend und Adapter laufen nicht sauber als zwei Prozesse."
    local backend_pattern
    [[ "$ACCELERATOR" == "metal" ]] && backend_pattern='wlk.*mlx-whisper' || backend_pattern='wlk.*faster-whisper'
    [[ "$(pgrep -f "$backend_pattern" | wc -l | tr -d ' ')" -eq 1 ]] || die "WhisperLiveKit läuft nicht genau einmal; das large-v3-Modell soll nur einmal resident sein."
    if [[ "$ACCELERATOR" == "cuda" ]]; then
        nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -qx "$backend_pid" || \
            die "Der residente WhisperLiveKit-Prozess erscheint nicht als NVIDIA-CUDA-Prozess."
    fi

    tmpdir="$(mktemp -d)"; pcm="$tmpdir/test.pcm"; events="$tmpdir/events.jsonl"
    make_test_pcm "$audio" "$pcm"
    stream_test_client "$pcm" "$events"
    grep -q '"type": "partial"' "$events" || die "Streaming-Test ohne partial-Ereignis."
    grep -q '"type": "confirmed"' "$events" || die "Streaming-Test ohne confirmed-Ereignis."
    rm -rf "$tmpdir"
}

test_tts() {
    local host port base tmpdir i pids=()
    host="$(http_host_from_config)"
    port="$(config_get tts.port)"; base="http://${host}:${port}"
    wait_http "$base/health" 300 || die "Piper-Healthcheck fehlgeschlagen."
    [[ "$(curl --silent --fail "$base/health" | jq -r '.workers')" == "$(config_get tts.workers)" ]] || die "Piper-Workerzahl stimmt nicht."
    tmpdir="$(mktemp -d)"
    curl --silent --show-error --fail "$base/v1/audio/speech" -H 'Content-Type: application/json' \
        --data '{"model":"piper","voice":"thorsten","input":"Dies ist ein verständlicher deutscher Test.","response_format":"wav"}' \
        >"$tmpdir/test.wav"
    [[ "$(wc -c <"$tmpdir/test.wav")" -gt 10000 ]] || die "Piper-Audiodatei ist zu klein."
    file "$tmpdir/test.wav" | grep -qi 'WAVE audio' || die "Piper-Ausgabe ist keine WAV-Datei."
    for i in 1 2 3 4; do
        curl --silent --show-error --fail "$base/v1/audio/speech" -H 'Content-Type: application/json' \
            --data "{\"input\":\"Parallele Sprachanfrage Nummer ${i}.\",\"response_format\":\"wav\"}" >"$tmpdir/$i.wav" &
        pids+=("$!")
    done
    for i in "${pids[@]}"; do wait "$i"; done
    for i in 1 2 3 4; do [[ "$(wc -c <"$tmpdir/$i.wav")" -gt 5000 ]] || die "Parallele Piper-Anfrage $i fehlgeschlagen."; done
    rm -rf "$tmpdir"
}

test_log_privacy() {
    local pattern='KIENZLEFON_LOG_CANARY_92741'
    if grep -R --binary-files=without-match -n "$pattern" "$LOG_DIR" 2>/dev/null; then
        die "Anfrageinhalt wurde in normalen Logs gefunden."
    fi
}

test_service_restart() {
    local role="$1"
    restart_role "$role"
    wait_role_ready "$role"
}

run_tests() {
    local roles=("$@") role testdir audio
    testdir="$(mktemp -d)"; audio="$testdir/de-test.wav"
    if contains_role asr "${roles[@]}"; then make_test_audio "$audio"; fi
    for role in "${roles[@]}"; do
        log "Teste $role ..."
        case "$role" in
            llm) test_llm ;;
            asr) test_asr "$audio" ;;
            tts) test_tts ;;
        esac
    done
    test_log_privacy
    for role in "${roles[@]}"; do test_service_restart "$role"; done
    rm -rf "$testdir"
    log "Alle ausgewählten Mindesttests bestanden."
}

# Liest enabled_roles ohne Python-Abhängigkeit. Für uninstall soll auch eine
# beschädigte/teilweise entfernte Python-Umgebung kein Hindernis sein.
read_enabled_roles_loose() {
    local line r
    [[ -r "$CONFIG_FILE" ]] || return 0
    line="$(grep -E '^[[:space:]]*enabled_roles[[:space:]]*=' "$CONFIG_FILE" 2>/dev/null | head -n1 || true)"
    for r in "${VALID_ROLES[@]}"; do
        [[ "$line" == *\"$r\"* ]] && printf '%s\n' "$r"
    done
}

update_config_remove_roles() {
    local remove_roles=("$@") current=() remaining=() r tmp json="[" first=1
    [[ -f "$CONFIG_FILE" ]] || return 0

    while IFS= read -r r; do
        [[ -n "$r" ]] && current+=("$r")
    done < <(read_enabled_roles_loose)

    for r in "${current[@]:-}"; do
        if ! contains_role "$r" "${remove_roles[@]}"; then
            remaining+=("$r")
        fi
    done

    for r in "${remaining[@]:-}"; do
        if (( first )); then first=0; else json+=", "; fi
        json+="\"${r}\""
    done
    json+="]"

    tmp="$(mktemp)"
    awk -v repl="enabled_roles = ${json}" '
        BEGIN {done=0}
        /^[[:space:]]*enabled_roles[[:space:]]*=/ {print repl; done=1; next}
        {print}
        END {if (!done) print repl}
    ' "$CONFIG_FILE" >"$tmp"
    sudo install -m 0644 -o root -g "$ROOT_GROUP" "$tmp" "$CONFIG_FILE"
    rm -f "$tmp"
}

service_process_patterns() {
    case "$1" in
        llm) printf '%s\n' "${PREFIX}/bin/llama-server" ;;
        asr)
            printf '%s\n' "${PREFIX}/scripts/asr_gateway.py"
            printf '%s\n' "${PREFIX}/python/asr-venv/bin/wlk"
            ;;
        asr-backend) printf '%s\n' "${PREFIX}/python/asr-venv/bin/wlk" ;;
        tts) printf '%s\n' "${PREFIX}/scripts/piper_service.py" ;;
    esac
}

terminate_managed_processes() {
    local role="$1" pattern pid i
    while IFS= read -r pattern; do
        [[ -n "$pattern" ]] || continue
        # pgrep -f ist hier absichtlich auf einen vollständigen verwalteten Pfad
        # unter /opt/kienzlefon-ai eingeschränkt; fremde qwen_tts-Installationen
        # werden dadurch nicht berührt.
        while IFS= read -r pid; do
            [[ -n "$pid" ]] || continue
            sudo kill -TERM "$pid" 2>/dev/null || true
        done < <(pgrep -f "$pattern" 2>/dev/null || true)

        for i in 1 2 3 4 5; do
            pgrep -f "$pattern" >/dev/null 2>&1 || break
            sleep 1
        done
        if pgrep -f "$pattern" >/dev/null 2>&1; then
            warn "Prozess für $role reagiert nicht auf SIGTERM; erzwinge Beendigung: $pattern"
            while IFS= read -r pid; do
                [[ -n "$pid" ]] || continue
                sudo kill -KILL "$pid" 2>/dev/null || true
            done < <(pgrep -f "$pattern" 2>/dev/null || true)
        fi
    done < <(service_process_patterns "$role")
}

remove_one_service_definition() {
    local role="$1"
    if [[ "$SERVICE_MANAGER" == "launchd" ]]; then
        local label plist
        label="$(role_label "$role")"
        plist="$(role_plist "$role")"

        # KeepAlive muss vor dem Beenden neutralisiert werden, sonst startet
        # launchd den Prozess sofort erneut.
        sudo launchctl disable "system/$label" >/dev/null 2>&1 || true

        if sudo launchctl print "system/$label" >/dev/null 2>&1; then
            if [[ -f "$plist" ]]; then
                sudo launchctl bootout system "$plist" >/dev/null 2>&1 || true
            fi
            sudo launchctl bootout "system/$label" >/dev/null 2>&1 || true
            sudo launchctl remove "$label" >/dev/null 2>&1 || true
        fi

        terminate_managed_processes "$role"
        sudo rm -f "$plist"

        if sudo launchctl print "system/$label" >/dev/null 2>&1; then
            die "LaunchDaemon $label ist nach uninstall noch registriert."
        fi
        # disable ist persistent. Nach Entfernen der plist den Override löschen,
        # damit eine spätere Neuinstallation wieder normal bootstrapen kann.
        sudo launchctl enable "system/$label" >/dev/null 2>&1 || true
    else
        local unit
        unit="$(role_systemd_name "$role")"
        sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
        terminate_managed_processes "$role"
        sudo rm -f "$(role_systemd_unit "$role")"
        sudo systemctl daemon-reload
        sudo systemctl reset-failed "$unit" >/dev/null 2>&1 || true
    fi
}

remove_role_service_definitions() {
    local role="$1"
    if [[ "$role" == "asr" ]]; then
        remove_one_service_definition asr
        remove_one_service_definition asr-backend
    else
        remove_one_service_definition "$role"
    fi
}

remove_role_files() {
    local role="$1"
    case "$role" in
        llm)
            sudo rm -f "$PREFIX/bin/llama-server" "$PREFIX/bin/llama-cli"
            sudo rm -rf "$PREFIX/src/llama.cpp"
            sudo rm -f "$PREFIX/models/Qwen_Qwen3.5-9B-Q6_K.gguf"
            sudo rm -f "$LOG_DIR"/llm.out.log "$LOG_DIR"/llm.err.log
            ;;
        asr)
            sudo rm -rf "$PREFIX/python/asr-venv"
            sudo rm -rf "$PREFIX/models/whisper-large-v3-mlx" "$PREFIX/models/whisper-large-v3-cuda"
            # Altpfade früher Debug-Versionen ebenfalls aufräumen.
            sudo rm -f "$PREFIX/models/large-v3.pt"
            sudo rm -rf "$DOWNLOAD_DIR/whisperlivekit-wheels"
            sudo rm -f "$PREFIX/scripts/asr_gateway.py"
            sudo rm -f "$LOG_DIR"/asr.out.log "$LOG_DIR"/asr.err.log \
                       "$LOG_DIR"/asr-backend.out.log "$LOG_DIR"/asr-backend.err.log
            ;;
        tts)
            sudo rm -rf "$PREFIX/python/tts-venv"
            sudo rm -f "$PREFIX/models/de_DE-thorsten-high.onnx" \
                       "$PREFIX/models/de_DE-thorsten-high.onnx.json"
            sudo rm -rf "$DOWNLOAD_DIR/piper-wheels"
            sudo rm -f "$PREFIX/scripts/piper_service.py"
            sudo rm -f "$LOG_DIR"/tts.out.log "$LOG_DIR"/tts.err.log
            ;;
    esac
}

cleanup_empty_managed_dirs() {
    local d
    for d in "$PREFIX/bin" "$PREFIX/src" "$PREFIX/models" "$PREFIX/python" "$PREFIX/downloads"; do
        [[ -d "$d" ]] || continue
        rmdir "$d" 2>/dev/null || true
    done
}

full_uninstall_cleanup() {
    # Alle bekannten Service-Definitionen entfernen, auch wenn die TOML fehlt
    # oder aus einer früheren Debug-Version stammt.
    remove_role_service_definitions llm
    remove_role_service_definitions asr

    sudo rm -rf "$PREFIX"
    sudo rm -f "$CONFIG_FILE" "$VERSIONS_FILE"
    sudo rmdir "$CONFIG_DIR" 2>/dev/null || true
    sudo rm -rf "$LOG_DIR"

    log "Vollständige Kienzlefon-AI-Installation dieses Installers entfernt."
    log "Nicht verändert: Homebrew/APT-Pakete, NVIDIA-Treiber, CUDA und externe Installationen wie /opt/kienzlefon/qwen3-tts."
}

uninstall_action() {
    local targets=() remaining=() configured_before=() r full=0 config_has_roles=0
    need_sudo

    if ((${#SELECTED_ROLES[@]} == 0)); then
        targets=("${VALID_ROLES[@]}")
        full=1
    else
        targets=("${SELECTED_ROLES[@]}")
        if contains_role llm "${targets[@]}" && contains_role asr "${targets[@]}" && contains_role tts "${targets[@]}"; then
            full=1
        fi
    fi

    if (( full )); then
        log "Deinstalliere alle von diesem Installer verwalteten Rollen ..."
        full_uninstall_cleanup
        return
    fi

    if [[ -f "$CONFIG_FILE" ]]; then
        while IFS= read -r r; do
            [[ -n "$r" ]] && configured_before+=("$r")
        done < <(read_enabled_roles_loose)
        ((${#configured_before[@]} > 0)) && config_has_roles=1
    fi

    for r in "${targets[@]}"; do
        log "Deinstalliere Rolle $r ..."
        remove_role_service_definitions "$r"
        remove_role_files "$r"
    done

    update_config_remove_roles "${targets[@]}"
    while IFS= read -r r; do
        [[ -n "$r" ]] && remaining+=("$r")
    done < <(read_enabled_roles_loose)

    # Nur dann automatisch auf vollständige Bereinigung wechseln, wenn vorher
    # tatsächlich eine erkennbare Rollenliste vorhanden war. Eine fehlende oder
    # beschädigte TOML darf bei einem gezielten Rollen-Uninstall niemals dazu
    # führen, dass versehentlich alle anderen Dateien entfernt werden.
    if (( config_has_roles == 1 && ${#remaining[@]} == 0 )); then
        log "Keine aktivierten Rollen verbleiben; entferne gemeinsame Installation."
        full_uninstall_cleanup
        return
    fi

    cleanup_empty_managed_dirs
    log "Rollen entfernt: $(roles_csv "${targets[@]}")"
    if [[ -f "$CONFIG_FILE" && $config_has_roles -eq 1 ]]; then
        log "Verbleibende Rollen: $(roles_csv "${remaining[@]}")"
        log "Konfiguration aktualisiert: $CONFIG_FILE"
    elif [[ -f "$CONFIG_FILE" ]]; then
        warn "Konfiguration enthielt keine erkennbare enabled_roles-Liste; nur die ausgewählten Rollen wurden entfernt."
    else
        warn "Konfiguration fehlt; nur die ausgewählten Rollen wurden entfernt."
    fi
}

resolve_target_roles() {
    local enabled=() r
    while IFS= read -r r; do
        [[ -n "$r" ]] && enabled+=("$r")
    done < <(read_enabled_roles)
    if ((${#SELECTED_ROLES[@]})); then
        for r in "${SELECTED_ROLES[@]}"; do
            contains_role "$r" "${enabled[@]}" || die "Rolle ist in der Konfiguration nicht aktiviert: $r"
        done
        TARGET_ROLES=("${SELECTED_ROLES[@]}")
    else
        TARGET_ROLES=("${enabled[@]}")
    fi
    ((${#TARGET_ROLES[@]})) || die "Keine aktivierten Rollen gefunden."
}

configure_action() {
    local enabled=() inferred=() r

    set_python_for_management
    [[ -x "$PYTHON" ]] || die "Python-Laufzeit fehlt. Zuerst installieren."
    [[ -f "$CONFIG_FILE" ]] || die "Konfiguration fehlt. Zuerst installieren."
    [[ -d "$PREFIX/scripts" && -f "$PREFIX/scripts/service_runner.py" ]] || \
        die "Verwaltetes Startskript fehlt. Zuerst installieren."

    need_sudo
    # Vor der Konfigurationsänderung auflösen, damit configure niemals eine noch
    # nicht installierte Rolle stillschweigend aktiviert.
    resolve_target_roles

    if ((${#SELECTED_ROLES[@]})); then
        [[ -z "$LLM_PORT_OVERRIDE$LLM_SLOTS_OVERRIDE$LLM_CONTEXT_OVERRIDE$LLM_KV_CACHE_OVERRIDE" ]] || \
            contains_role llm "${TARGET_ROLES[@]}" || die "LLM-Optionen erfordern --role llm."
        [[ -z "$ASR_PORT_OVERRIDE$ASR_BACKEND_PORT_OVERRIDE$ASR_BACKEND_BIND_OVERRIDE$ASR_FRAME_THRESHOLD_OVERRIDE" ]] || \
            contains_role asr "${TARGET_ROLES[@]}" || die "ASR-Optionen erfordern --role asr."
        [[ -z "$TTS_PORT_OVERRIDE$PIPER_WORKERS_OVERRIDE$PIPER_LENGTH_SCALE_OVERRIDE" ]] || \
            contains_role tts "${TARGET_ROLES[@]}" || die "TTS-Optionen erfordern --role tts."
        if [[ -n "$BIND_OVERRIDE" ]]; then
            while IFS= read -r r; do
                [[ -n "$r" ]] && enabled+=("$r")
            done < <(read_enabled_roles)
            for r in "${enabled[@]}"; do
                contains_role "$r" "${TARGET_ROLES[@]}" || \
                    die "--bind ändert alle öffentlichen Dienste; --role weglassen oder alle aktivierten Rollen auswählen."
            done
        fi
    else
        # Ohne --role aus den rollenbezogenen Änderungen die kleinste nötige
        # Neustartmenge ableiten. Eine globale Bindungsänderung betrifft alle.
        if [[ -z "$BIND_OVERRIDE" ]]; then
            [[ -z "$LLM_PORT_OVERRIDE$LLM_SLOTS_OVERRIDE$LLM_CONTEXT_OVERRIDE$LLM_KV_CACHE_OVERRIDE" ]] || inferred+=(llm)
            [[ -z "$ASR_PORT_OVERRIDE$ASR_BACKEND_PORT_OVERRIDE$ASR_BACKEND_BIND_OVERRIDE$ASR_FRAME_THRESHOLD_OVERRIDE" ]] || inferred+=(asr)
            [[ -z "$TTS_PORT_OVERRIDE$PIPER_WORKERS_OVERRIDE$PIPER_LENGTH_SCALE_OVERRIDE" ]] || inferred+=(tts)
            if ((${#inferred[@]})); then
                for r in "${inferred[@]}"; do
                    contains_role "$r" "${TARGET_ROLES[@]}" || die "Rolle ist in der Konfiguration nicht aktiviert: $r"
                done
                TARGET_ROLES=("${inferred[@]}")
            fi
        fi
    fi

    write_or_update_config
    validate_runtime_config
    write_service_runner

    for r in "${TARGET_ROLES[@]}"; do
        restart_role "$r"
        wait_role_ready "$r"
    done

    log "Konfiguration ohne Neuinstallation aktualisiert."
    log "Neu gestartete Rollen: $(roles_csv "${TARGET_ROLES[@]}")"
    log "Konfiguration: $CONFIG_FILE"
}

install_action() {
    local roles_to_install=() enabled=() r need_llama=0 need_asr=0 need_tts=0
    install_platform_dependencies
    [[ -x "$PYTHON" ]] || die "Python-Laufzeit fehlt: $PYTHON"
    ensure_managed_dirs
    write_versions_file_if_missing
    load_versions_file

    if [[ ! -f "$CONFIG_FILE" && ${#SELECTED_ROLES[@]} -eq 0 ]]; then
        die "Bei der Erstinstallation mindestens eine --role angeben, zum Beispiel --role all."
    fi
    write_or_update_config
    validate_runtime_config
    while IFS= read -r r; do
        [[ -n "$r" ]] && enabled+=("$r")
    done < <(read_enabled_roles)
    if ((${#SELECTED_ROLES[@]})); then roles_to_install=("${SELECTED_ROLES[@]}"); else roles_to_install=("${enabled[@]}"); fi
    ((${#roles_to_install[@]})) || die "Keine Rollen zur Installation ausgewählt."

    for r in "${roles_to_install[@]}"; do
        [[ "$r" == "llm" ]] && need_llama=1
        [[ "$r" == "asr" ]] && need_asr=1
        [[ "$r" == "tts" ]] && need_tts=1
    done

    if [[ "$PLATFORM" == "ubuntu" && ( $need_llama -eq 1 || $need_asr -eq 1 ) ]]; then
        command -v nvidia-smi >/dev/null 2>&1 || die "Für LLM/ASR unter Ubuntu ist ein vorhandener NVIDIA-Treiber erforderlich (nvidia-smi fehlt)."
        nvidia-smi >/dev/null 2>&1 || die "nvidia-smi funktioniert nicht. GPU-Treiber zuerst reparieren."
        command -v nvcc >/dev/null 2>&1 || die "CUDA Toolkit/nvcc fehlt. In dieser Version wird CUDA vorausgesetzt, aber nicht vom Installer installiert."
        log "NVIDIA/CUDA-Voraussetzungen erkannt: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1); nvcc $(nvcc --version | tail -n1)"
    fi

    (( need_llama == 0 )) || build_llama_cpp
    (( need_asr == 0 )) || install_asr_python
    (( need_tts == 0 )) || install_piper_python

    for r in "${roles_to_install[@]}"; do download_role_models "$r"; done
    write_runtime_scripts
    for r in "${enabled[@]}"; do
        if [[ "$r" == "asr" ]]; then write_service_definition asr-backend; fi
        write_service_definition "$r"
    done

    if (( NO_START == 0 )); then
        # Geänderte Service-Definitionen werden durch sauberes Stop/Start übernommen.
        for r in "${enabled[@]}"; do restart_role "$r"; done
        for r in "${enabled[@]}"; do wait_role_ready "$r"; done
        if (( SKIP_TESTS == 0 )); then run_tests "${enabled[@]}"; fi
    fi

    log "Installation abgeschlossen."
    log "Plattform: $PLATFORM / Beschleuniger: $ACCELERATOR / Dienste: $SERVICE_MANAGER"
    log "Konfiguration: $CONFIG_FILE"
    log "Status: $0 --action status"
}

# Für install/configure/uninstall gelten eigene Voraussetzungen. Uninstall ist bewusst
# unabhängig von einer noch funktionierenden Python-Umgebung oder TOML-Validierung.
if [[ "$ACTION" == "install" ]]; then
    install_action
    exit 0
fi

if [[ "$ACTION" == "uninstall" ]]; then
    uninstall_action
    exit 0
fi

if [[ "$ACTION" == "configure" ]]; then
    configure_action
    exit 0
fi

set_python_for_management
[[ -x "$PYTHON" ]] || die "Python-Laufzeit fehlt. Zuerst installieren."
[[ -f "$CONFIG_FILE" ]] || die "Konfiguration fehlt. Zuerst installieren."
validate_runtime_config
need_sudo
resolve_target_roles

case "$ACTION" in
    start)
        for role in "${TARGET_ROLES[@]}"; do start_role "$role"; wait_role_ready "$role"; done
        ;;
    stop)
        for role in "${TARGET_ROLES[@]}"; do stop_role "$role"; done
        ;;
    restart)
        for role in "${TARGET_ROLES[@]}"; do restart_role "$role"; wait_role_ready "$role"; done
        ;;
    status)
        for role in "${TARGET_ROLES[@]}"; do status_role "$role"; done
        ;;
    test)
        run_tests "${TARGET_ROLES[@]}"
        ;;
esac
__KZF_CORE_V2_PAYLOAD__
}

write_qwen_payload() {
  cat <<'__KZF_QWEN_V2_PAYLOAD__'
#!/bin/bash
# install-kienzlefon-qwen3-tts-v2.0.sh
#
# Cross-platform standalone installer for the native Qwen3-TTS 0.6B
# CustomVoice service and one-shot announcement generator used by the
# Kienzlefon project.
#
# Supported targets:
#   - macOS on Apple Silicon (arm64): CPU + Metal build
#   - Ubuntu Linux on x86_64:        CPU + NVIDIA CUDA build
#   - Debian 12/13 on x86_64:        offline-only CPU + optional NVIDIA CUDA
#
# Runtime defaults:
#   macOS Apple Silicon: CPU / INT8 / 4 threads / batch size 1 / TCP 8182
#   Ubuntu + NVIDIA CUDA: CUDA / INT8 / batch size 1 / TCP 8182
#   Offline-only:        pause detected ASR units, then CUDA when usable,
#                        otherwise CPU / INT8 / no TCP port
#
# On Ubuntu, CUDA is the normal service backend whenever this CUDA-enabled
# installer is used. CPU remains available as a benchmark/fallback backend.
#
# Scope:
#   - installs/builds https://github.com/gabriele-mastrapasqua/qwen3-tts
#   - downloads ONLY Qwen3-TTS-12Hz-0.6B-CustomVoice
#   - keeps model data separate from source code
#   - installs a persistent HTTP service (launchd or systemd)
#   - tests German/uncle_fu WAV and streaming PCM endpoints
#   - installs healthcheck / benchmark / control commands
#   - benchmarks CPU INT8/INT8 plus Metal INT8/INT8 or CUDA INT8/INT8
#   - optionally installs a non-resident one-shot generator without a service
#
# Explicitly NOT in scope:
#   - Piper selection/fallback
#   - Whisper / llama.cpp changes
#   - Kienzlefon call routing
#   - automatic git updates or commit pinning
#   - Docker, Python or PyTorch TTS runtimes
#   - installing/upgrading NVIDIA drivers or the CUDA Toolkit
#
# Ubuntu CUDA policy:
#   The installer installs ordinary build dependencies (OpenBLAS, compiler, etc.)
#   through apt, but NEVER modifies NVIDIA drivers or CUDA. A working nvidia-smi
#   and nvcc are required on Ubuntu so the delivered binary really has CUDA
#   support. CUDA_HOME can be overridden with --cuda-home.
#
# The upstream HTTP server currently binds to all IPv4 interfaces. This installer
# intentionally does not patch that behaviour.

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

SCRIPT_NAME="$(basename "$0")"
VERSION="2.0"

REPO_URL="https://github.com/gabriele-mastrapasqua/qwen3-tts.git"
REPO_COMMIT="328ab9cb241774572bb59917af199bdf64a17227"
BASE_DIR="/opt/kienzlefon/qwen3-tts"
SRC_DIR="${BASE_DIR}/src"
BIN_DIR="${BASE_DIR}/bin"
TOOLS_DIR="${BASE_DIR}/tools"
MODEL_BASE="/opt/kienzlefon/models"
MODEL_DIR="${MODEL_BASE}/qwen3-tts-0.6b-customvoice"
LOG_DIR="/var/log/kienzlefon/qwen3-tts"
ETC_DIR="/etc/kienzlefon"
STATE_DIR="/var/lib/kienzlefon/qwen3-tts"

BINARY="${BIN_DIR}/qwen_tts"
CPU_BINARY="${BIN_DIR}/qwen_tts-cpu"
CUDA_BINARY="${BIN_DIR}/qwen_tts-cuda"
TTFA_HELPER="${BIN_DIR}/kienzlefon-qwen3-tts-ttfa"
HEALTH_CMD="/usr/local/bin/kienzlefon-qwen3-tts-healthcheck"
BENCH_CMD="/usr/local/bin/kienzlefon-qwen3-tts-benchmark"
CTL_CMD="/usr/local/bin/kienzlefon-qwen3-tts-ctl"
GENERATE_CMD="/usr/local/bin/kienzlefon-qwen3-tts-generate"
ENV_FILE="${ETC_DIR}/qwen3-tts.env"
OFFLINE_ENV_FILE="${ETC_DIR}/qwen3-tts-offline.env"
GENERATE_LOCK="${STATE_DIR}/generate.lock"

LABEL="com.kienzlefon.qwen3-tts"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
SYSTEMD_UNIT_NAME="kienzlefon-qwen3-tts.service"
SYSTEMD_UNIT="/etc/systemd/system/${SYSTEMD_UNIT_NAME}"

PORT=8182
THREADS=4
THREADS_EXPLICIT=0
BATCH_SIZE=1
RUN_BENCHMARK=1
MIN_RAM_GIB=8
MIN_GENERATE_AVAILABLE_KIB=$((5 * 1024 * 1024))
STOP_TIMEOUT_SECONDS=60
READINESS_TIMEOUT_SECONDS=300
CUDA_HOME_OVERRIDE=""
UNINSTALL=0
KEEP_MODEL=0
OFFLINE_ONLY=0

PLATFORM=""
ARCH=""
OS_VERSION=""
SERVICE_KIND=""
CUDA_HOME=""
CUDA_LIBDIR=""
CUDA_ARCH=""
CUDA_GPU_NAME=""
CUDA_AVAILABLE=0
DISTRO_ID=""
PAUSE_UNITS=()

MAINTENANCE_MARKER="/run/kienzlefon/asr-maintenance"
CLASSIC_WORKER_UNIT="kienzlefon-worker.service"
CLASSIC_STATUS_CMD="/opt/kienzlefon/venv/bin/kienzlefon-status"
CLASSIC_STATUS_PYTHON="/opt/kienzlefon/venv/bin/python"
CLASSIC_CONFIG="/etc/kienzlefon/kienzlefon.toml"
CLASSIC_HEARTBEAT="/run/kienzlefon/whisper-health.json"

STANDARD_MODE="CPU INT8"  # set to CUDA INT8 on Ubuntu after platform detection
MODEL_HF_ID="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
TEST_TEXT="Guten Tag. Dies ist ein reproduzierbarer Test der natürlichen Sprachausgabe für Kienzlefon."
TEST_SEED=42

ORIGINAL_ARGS=("$@")
CLEANUP_STAGE=""
CLEANUP_TMP=""

usage() {
  cat <<USAGE
Usage: sudo ./${SCRIPT_NAME} [options]

Supported platforms:
  macOS Apple Silicon arm64     -> CPU + Metal
  Ubuntu Linux x86_64          -> CPU + NVIDIA CUDA
  Debian 12/13 x86_64          -> offline-only CPU + optional NVIDIA CUDA

Debian offline-only uses 2 CPU threads unless --threads is supplied.

Options:
  --port N             HTTP port; service mode only (default: ${PORT})
  --threads N          CPU worker threads (default: ${THREADS})
  --batch-size N       Server request batch size; service mode only (default: ${BATCH_SIZE})
  --cuda-home PATH     Linux only: explicit CUDA Toolkit prefix
  --skip-benchmark     Service mode only: install + healthcheck without benchmark
  --offline-only       Install only the non-resident local WAV generator;
                       create no service, autostart, HTTP server, or listener
  --uninstall          Completely remove this Qwen3-TTS installation
  --keep-model         With --uninstall: keep the downloaded 0.6B model
  -h, --help           Show this help

Default service mode:
  macOS Apple Silicon : CPU / INT8 / ${THREADS} threads / batch size ${BATCH_SIZE}
  Ubuntu + NVIDIA CUDA: CUDA / INT8 / batch size ${BATCH_SIZE}

CPU remains available on Ubuntu for comparison/fallback. Ubuntu requires an
already working NVIDIA driver (nvidia-smi) and CUDA Toolkit (nvcc). This installer
does not install or change either one.

Offline-only mode:
  sudo ./${SCRIPT_NAME} --offline-only

The offline generator always includes a CPU-only binary. On Ubuntu it additionally
uses CUDA when a working NVIDIA driver, CUDA Toolkit, and CUDA self-test are
available. The same optional CUDA preference applies to Debian. A pure offline-only
installation never creates a Qwen service and never opens port ${PORT}. During each
generation it temporarily stops only detected, positively listed Kienzlefon ASR
units, then restores exactly the units that were active before. Source, build
dependencies, and model are installed normally and may require network access.

Installation validation performs one real one-shot generation. Low currently
available RAM does not block installation before ASR units are stopped; the hard
5 GiB MemAvailable check runs only immediately before Qwen generation.

Uninstall:
  sudo ./${SCRIPT_NAME} --uninstall
  sudo ./${SCRIPT_NAME} --uninstall --keep-model

Uninstall never removes NVIDIA drivers, CUDA, Xcode tools, compilers, apt packages,
or other shared system dependencies.
USAGE
}

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

cleanup_transient() {
  set +e
  if [[ -n "${CLEANUP_STAGE:-}" && -d "${CLEANUP_STAGE}" ]]; then
    case "$CLEANUP_STAGE" in
      "${MODEL_BASE}"/.qwen3-tts-0.6b-customvoice.download.*) rm -rf -- "$CLEANUP_STAGE" ;;
    esac
  fi
  if [[ -n "${CLEANUP_TMP:-}" && -d "${CLEANUP_TMP}" ]]; then
    case "$CLEANUP_TMP" in /tmp/kienzlefon-qwen-*) rm -rf -- "$CLEANUP_TMP" ;; esac
  fi
  set -e
}

die() {
  local msg="$*"
  cleanup_transient
  printf '[ERROR] %s\n' "$msg" >&2
  exit 1
}

on_error() {
  local rc=$?
  local line=${1:-?}
  cleanup_transient
  set +e
  printf '\n[ERROR] Installation failed at line %s (exit %s).\n' "$line" "$rc" >&2
  if (( OFFLINE_ONLY == 1 )); then
    printf '[ERROR] Offline-only mode created no service log containing the TTS input text.\n' >&2
  else
    printf '[ERROR] Service logs are under: %s\n' "$LOG_DIR" >&2
  fi
  exit "$rc"
}
trap 'on_error $LINENO' ERR

is_uint() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -ge 2 ]] || die "--port requires a value"
      PORT="$2"; shift 2 ;;
    --threads)
      [[ $# -ge 2 ]] || die "--threads requires a value"
      THREADS="$2"; THREADS_EXPLICIT=1; shift 2 ;;
    --batch-size)
      [[ $# -ge 2 ]] || die "--batch-size requires a value"
      BATCH_SIZE="$2"; shift 2 ;;
    --cuda-home)
      [[ $# -ge 2 ]] || die "--cuda-home requires a value"
      CUDA_HOME_OVERRIDE="$2"; shift 2 ;;
    --skip-benchmark)
      RUN_BENCHMARK=0; shift ;;
    --offline-only)
      OFFLINE_ONLY=1; shift ;;
    --uninstall)
      UNINSTALL=1; shift ;;
    --keep-model)
      KEEP_MODEL=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "Unknown option: $1" ;;
  esac
done

if (( KEEP_MODEL == 1 && UNINSTALL == 0 )); then
  die "--keep-model is only valid together with --uninstall"
fi

if (( OFFLINE_ONLY == 1 && UNINSTALL == 1 )); then
  die "--offline-only cannot be combined with --uninstall"
fi

is_uint "$PORT" || die "Port must be an integer"
is_uint "$THREADS" || die "Threads must be an integer"
is_uint "$BATCH_SIZE" || die "Batch size must be an integer"
(( PORT >= 1 && PORT <= 65535 )) || die "Port must be between 1 and 65535"
(( THREADS >= 1 && THREADS <= 64 )) || die "Threads must be between 1 and 64"
(( BATCH_SIZE >= 1 && BATCH_SIZE <= 64 )) || die "Batch size must be between 1 and 64"

# Re-exec as root because installation uses system locations.
if [[ "${EUID}" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "This installer requires root privileges and sudo was not found."
  log "Root privileges are required; invoking sudo."
  exec sudo -- "$0" "${ORIGINAL_ARGS[@]}"
fi

remove_file_if_present() {
  local p="$1"
  if [[ -e "$p" || -L "$p" ]]; then
    rm -f -- "$p"
    log "Removed: $p"
  fi
}

remove_dir_if_present() {
  local p="$1"
  if [[ -d "$p" ]]; then
    rm -rf -- "$p"
    log "Removed: $p"
  fi
}

uninstall_service_only() {
  local kernel
  kernel="$(uname -s)"
  case "$kernel" in
    Darwin)
      if command -v launchctl >/dev/null 2>&1; then
        if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
          log "Stopping launchd service ${LABEL}..."
          launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
          local i
          for ((i=0; i<50; i++)); do
            launchctl print "system/${LABEL}" >/dev/null 2>&1 || break
            sleep 0.2
          done
        fi
      fi
      remove_file_if_present "$PLIST"
      ;;
    Linux)
      if command -v systemctl >/dev/null 2>&1; then
        log "Stopping/disabling systemd service ${SYSTEMD_UNIT_NAME} if present..."
        systemctl stop "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
        systemctl disable "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
      fi
      remove_file_if_present "$SYSTEMD_UNIT"
      if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl reset-failed "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
      fi
      ;;
    *)
      warn "Unknown OS '$kernel'; removing files but no service manager action can be guaranteed."
      remove_file_if_present "$PLIST"
      remove_file_if_present "$SYSTEMD_UNIT"
      ;;
  esac
}

uninstall_all() {
  log "Starting Kienzlefon Qwen3-TTS uninstall v${VERSION}"

  uninstall_service_only

  remove_file_if_present "$HEALTH_CMD"
  remove_file_if_present "$BENCH_CMD"
  remove_file_if_present "$CTL_CMD"
  remove_file_if_present "$GENERATE_CMD"
  remove_file_if_present "$ENV_FILE"
  remove_file_if_present "$OFFLINE_ENV_FILE"

  # Everything below BASE_DIR belongs solely to this installer.
  remove_dir_if_present "$BASE_DIR"
  remove_dir_if_present "$STATE_DIR"
  remove_dir_if_present "$LOG_DIR"

  # Remove interrupted/staged model downloads created by this installer.
  if [[ -d "$MODEL_BASE" ]]; then
    local p
    shopt -s nullglob
    for p in \
      "${MODEL_BASE}"/.qwen3-tts-0.6b-customvoice.download.* \
      "${MODEL_DIR}".incomplete.*; do
      [[ -e "$p" ]] || continue
      rm -rf -- "$p"
      log "Removed: $p"
    done
    shopt -u nullglob
  fi

  if (( KEEP_MODEL == 1 )); then
    if [[ -d "$MODEL_DIR" ]]; then
      log "Keeping model by request: $MODEL_DIR"
    else
      log "No model directory present to keep."
    fi
  else
    remove_dir_if_present "$MODEL_DIR"
  fi

  # Remove only empty parent directories; never touch unrelated Kienzlefon data.
  rmdir "$MODEL_BASE" >/dev/null 2>&1 || true
  rmdir "$ETC_DIR" >/dev/null 2>&1 || true
  rmdir "/var/lib/kienzlefon" >/dev/null 2>&1 || true
  rmdir "/var/log/kienzlefon" >/dev/null 2>&1 || true
  rmdir "/opt/kienzlefon" >/dev/null 2>&1 || true

  cat <<EOF_UNINSTALL

====================================================================
Kienzlefon Qwen3-TTS uninstall complete
====================================================================
Service            : removed/stopped
Helper commands    : removed
Source/binary      : removed
Configuration      : removed
State              : removed
Logs               : removed
Model              : $([[ "$KEEP_MODEL" -eq 1 ]] && echo "kept at ${MODEL_DIR}" || echo "removed")
System dependencies: untouched
NVIDIA/CUDA        : untouched
====================================================================
EOF_UNINSTALL
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

file_size() {
  if [[ "$PLATFORM" == "macos" ]]; then
    stat -f '%z' "$1"
  else
    stat -c '%s' "$1"
  fi
}

validate_wav() {
  local f="$1"
  [[ -f "$f" ]] || return 1
  local size
  size="$(file_size "$f")"
  (( size > 44 )) || return 1
  [[ "$(dd if="$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "$(dd if="$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
  return 0
}

model_is_complete() {
  local d="$1"
  local required=(
    "config.json"
    "generation_config.json"
    "tokenizer_config.json"
    "preprocessor_config.json"
    "model.safetensors"
    "vocab.json"
    "merges.txt"
    "speech_tokenizer/config.json"
    "speech_tokenizer/configuration.json"
    "speech_tokenizer/model.safetensors"
    "speech_tokenizer/preprocessor_config.json"
  )
  local f size
  for f in "${required[@]}"; do
    [[ -s "${d}/${f}" ]] || return 1
  done

  # Conservative size thresholds catch common interrupted downloads without
  # coupling the installer to exact model file sizes.
  size="$(file_size "${d}/model.safetensors")"
  (( size >= 100000000 )) || return 1
  size="$(file_size "${d}/speech_tokenizer/model.safetensors")"
  (( size >= 10000000 )) || return 1
  return 0
}

wait_for_health() {
  local url="$1"
  local attempts="${2:-180}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 2 "${url}/v1/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

detect_platform() {
  local kernel
  kernel="$(uname -s)"
  ARCH="$(uname -m)"

  case "$kernel" in
    Darwin)
      PLATFORM="macos"
      SERVICE_KIND="launchd"
      [[ "$ARCH" == "arm64" ]] || die "macOS support requires Apple Silicon arm64; detected ${ARCH}."
      OS_VERSION="$(sw_vers -productVersion 2>/dev/null || true)"
      ;;
    Linux)
      [[ -r /etc/os-release ]] || die "Linux detected, but /etc/os-release is missing."
      # shellcheck disable=SC1091
      . /etc/os-release
      DISTRO_ID="${ID:-unknown}"
      [[ "$ARCH" == "x86_64" ]] || die "Linux support currently requires x86_64; detected ${ARCH}."
      SERVICE_KIND="systemd"
      OS_VERSION="${VERSION_ID:-unknown}"
      case "$DISTRO_ID" in
        ubuntu)
          PLATFORM="ubuntu"
          STANDARD_MODE="CUDA INT8"
          ;;
        debian)
          case "$OS_VERSION" in
            12|13) ;;
            *) die "Debian support is limited to versions 12 and 13; detected ${OS_VERSION}." ;;
          esac
          (( OFFLINE_ONLY == 1 )) || die "Debian ${OS_VERSION} is supported only together with --offline-only."
          PLATFORM="debian"
          STANDARD_MODE="CPU INT8"
          (( THREADS_EXPLICIT == 1 )) || THREADS=2
          ;;
        *)
          die "Linux support is limited to Ubuntu and Debian 12/13; detected ID='${DISTRO_ID}'."
          ;;
      esac
      ;;
    *)
      die "Unsupported operating system: ${kernel}"
      ;;
  esac
}

check_ram() {
  local ram_bytes ram_gib available_kib=0
  if [[ "$PLATFORM" == "macos" ]]; then
    ram_bytes="$(sysctl -n hw.memsize)"
  else
    ram_bytes="$(awk '/^MemTotal:/ {printf "%.0f", $2 * 1024}' /proc/meminfo)"
  fi
  ram_gib=$(( ram_bytes / 1073741824 ))
  if [[ "$PLATFORM" != "macos" ]]; then
    available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    is_uint "$available_kib" || available_kib=0
  fi

  if (( OFFLINE_ONLY == 1 )); then
    log "RAM detected: ${ram_gib} GiB total; current free memory does not block offline installation."
    if (( available_kib > 0 && available_kib < MIN_GENERATE_AVAILABLE_KIB )); then
      warn "Only $((available_kib / 1024)) MiB is currently available. ASR units will be stopped before the installation generation test; the 5 GiB check runs afterwards."
    fi
    return 0
  fi

  (( ram_gib >= MIN_RAM_GIB )) || die "At least ${MIN_RAM_GIB} GiB RAM is required; detected ${ram_gib} GiB."
  log "RAM detected: ${ram_gib} GiB"
}

install_linux_build_dependencies() {
  log "Installing/checking Linux build dependencies (NVIDIA/CUDA are intentionally untouched)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  local packages=(
    build-essential
    ca-certificates
    curl
    git
    libopenblas-dev
  )
  if (( OFFLINE_ONLY == 0 )); then
    packages+=(lsof)
  fi
  apt-get install -y --no-install-recommends "${packages[@]}"
}

probe_cuda_optional() {
  [[ "$PLATFORM" == "ubuntu" || "$PLATFORM" == "debian" ]] || return 1

  CUDA_AVAILABLE=0
  CUDA_HOME=""
  CUDA_LIBDIR=""
  CUDA_ARCH=""
  CUDA_GPU_NAME=""

  if ! command -v nvidia-smi >/dev/null 2>&1; then
    warn "No nvidia-smi found; offline generation will use the CPU backend."
    return 1
  fi
  if ! nvidia-smi >/dev/null 2>&1; then
    warn "nvidia-smi cannot communicate with the NVIDIA driver; offline generation will use CPU."
    return 1
  fi

  CUDA_GPU_NAME="$(nvidia-smi -i "${KIENZLEFON_SELECTED_GPU_UUID:?}" --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "$CUDA_GPU_NAME" ]] || CUDA_GPU_NAME="NVIDIA GPU"

  local nvcc_path="" resolved=""
  if [[ -n "$CUDA_HOME_OVERRIDE" ]]; then
    CUDA_HOME="${CUDA_HOME_OVERRIDE%/}"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif command -v nvcc >/dev/null 2>&1; then
    nvcc_path="$(command -v nvcc)"
    if command -v readlink >/dev/null 2>&1; then
      resolved="$(readlink -f "$nvcc_path" 2>/dev/null || true)"
      [[ -n "$resolved" ]] && nvcc_path="$resolved"
    fi
    CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
  elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
    CUDA_HOME="/usr/local/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif [[ -x /opt/cuda/bin/nvcc ]]; then
    CUDA_HOME="/opt/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  else
    warn "NVIDIA driver found, but no CUDA Toolkit compiler (nvcc); offline generation will use CPU."
    return 1
  fi

  if [[ ! -x "$nvcc_path" || ! -d "${CUDA_HOME}/include" ]]; then
    warn "CUDA Toolkit at '${CUDA_HOME}' is incomplete; offline generation will use CPU."
    CUDA_HOME=""
    return 1
  fi

  if [[ -d "${CUDA_HOME}/lib64" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib64"
  elif [[ -d "${CUDA_HOME}/lib" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib"
  else
    warn "CUDA library directory is missing below '${CUDA_HOME}'; offline generation will use CPU."
    CUDA_HOME=""
    return 1
  fi

  local cc
  cc="$(nvidia-smi -i "${KIENZLEFON_SELECTED_GPU_UUID:?}" --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
  if [[ ! "$cc" =~ ^[0-9]+\.[0-9]+$ ]]; then
    warn "Could not determine NVIDIA compute capability; offline generation will use CPU."
    CUDA_HOME=""
    CUDA_LIBDIR=""
    return 1
  fi

  CUDA_ARCH="sm_${cc/./}"
  CUDA_AVAILABLE=1
  log "Optional CUDA backend detected: ${CUDA_GPU_NAME} (compute capability ${cc}, build arch ${CUDA_ARCH})"
  log "CUDA Toolkit: ${CUDA_HOME}"
  "$nvcc_path" --version | tail -n 1 || true
  return 0
}

detect_cuda() {
  [[ "$PLATFORM" == "ubuntu" ]] || return 0

  require_cmd nvidia-smi
  nvidia-smi >/dev/null 2>&1 || die "nvidia-smi exists but cannot communicate with the NVIDIA driver. CUDA setup is not healthy."

  CUDA_GPU_NAME="$(nvidia-smi -i "${KIENZLEFON_SELECTED_GPU_UUID:?}" --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "$CUDA_GPU_NAME" ]] || CUDA_GPU_NAME="NVIDIA GPU"

  local nvcc_path
  if [[ -n "$CUDA_HOME_OVERRIDE" ]]; then
    CUDA_HOME="${CUDA_HOME_OVERRIDE%/}"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif command -v nvcc >/dev/null 2>&1; then
    nvcc_path="$(command -v nvcc)"
    # Resolve symlinks where possible, then take <prefix>/bin/nvcc -> <prefix>.
    if command -v readlink >/dev/null 2>&1; then
      local resolved
      resolved="$(readlink -f "$nvcc_path" 2>/dev/null || true)"
      [[ -n "$resolved" ]] && nvcc_path="$resolved"
    fi
    CUDA_HOME="$(dirname "$(dirname "$nvcc_path")")"
  elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
    CUDA_HOME="/usr/local/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  elif [[ -x /opt/cuda/bin/nvcc ]]; then
    CUDA_HOME="/opt/cuda"
    nvcc_path="${CUDA_HOME}/bin/nvcc"
  else
    die "CUDA Toolkit compiler nvcc was not found. Install/configure CUDA first; this installer deliberately does not modify CUDA or NVIDIA drivers."
  fi

  [[ -x "$nvcc_path" ]] || die "nvcc is not executable at ${nvcc_path}"
  [[ -d "${CUDA_HOME}/include" ]] || die "CUDA include directory missing: ${CUDA_HOME}/include"

  if [[ -d "${CUDA_HOME}/lib64" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib64"
  elif [[ -d "${CUDA_HOME}/lib" ]]; then
    CUDA_LIBDIR="${CUDA_HOME}/lib"
  else
    die "CUDA library directory not found below ${CUDA_HOME}"
  fi

  # Build for the installed machine's first GPU rather than upstream's broad
  # multi-arch default. This both shortens compilation and avoids asking older
  # toolkits to understand unrelated future architectures (e.g. sm_120).
  local cc
  cc="$(nvidia-smi -i "${KIENZLEFON_SELECTED_GPU_UUID:?}" --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
  if [[ "$cc" =~ ^[0-9]+\.[0-9]+$ ]]; then
    CUDA_ARCH="sm_${cc/./}"
  else
    die "Could not determine NVIDIA compute capability with nvidia-smi; refusing to guess a CUDA architecture."
  fi

  log "NVIDIA GPU: ${CUDA_GPU_NAME} (compute capability ${cc}, build arch ${CUDA_ARCH})"
  log "CUDA Toolkit: ${CUDA_HOME}"
  "$nvcc_path" --version | tail -n 1 || true
  CUDA_AVAILABLE=1
}

check_platform_and_tools() {
  detect_platform
  log "Detected platform: ${PLATFORM} ${OS_VERSION} / ${ARCH}"

  if [[ "$PLATFORM" == "ubuntu" || "$PLATFORM" == "debian" ]]; then
    require_cmd apt-get
    install_linux_build_dependencies
  fi

  require_cmd awk
  require_cmd cat
  require_cmd cp
  require_cmd curl
  require_cmd dd
  require_cmd dirname
  require_cmd git
  require_cmd grep
  require_cmd head
  require_cmd install
  require_cmd make
  require_cmd mkdir
  require_cmd mktemp
  require_cmd mv
  require_cmd od
  require_cmd sed
  require_cmd stat
  require_cmd tr
  require_cmd wc

  if (( OFFLINE_ONLY == 0 )); then
    require_cmd lsof
    require_cmd ps
    require_cmd tail
    require_cmd tee
  fi

  if [[ "$PLATFORM" == "macos" ]]; then
    require_cmd clang
    require_cmd xcode-select
    require_cmd sysctl
    if (( OFFLINE_ONLY == 0 )); then
      require_cmd plutil
      require_cmd launchctl
    fi
    xcode-select -p >/dev/null 2>&1 || die "Xcode Command Line Tools are not active. Run: xcode-select --install"
    clang --version >/dev/null 2>&1 || die "clang is not usable"
  else
    require_cmd gcc
    require_cmd ldd
    require_cmd systemctl
    gcc --version >/dev/null 2>&1 || die "gcc is not usable"
    if (( OFFLINE_ONLY == 1 )); then
      probe_cuda_optional || true
    else
      detect_cuda
    fi
  fi

  make --version >/dev/null 2>&1 || die "make is not usable"
  check_ram
}

prepare_directories() {
  log "Preparing directories..."
  mkdir -p "$BASE_DIR" "$BIN_DIR" "$TOOLS_DIR" "$MODEL_BASE" "$LOG_DIR" "$ETC_DIR" "$STATE_DIR" /usr/local/bin
  chmod 0755 "$BASE_DIR" "$BIN_DIR" "$TOOLS_DIR" "$MODEL_BASE" "$LOG_DIR" "$ETC_DIR" "$STATE_DIR" /usr/local/bin
}

systemd_unit_exists() {
  local unit="$1" load_state
  [[ "$PLATFORM" != "macos" ]] || return 1
  load_state="$(systemctl show "$unit" -p LoadState --value 2>/dev/null || true)"
  [[ -n "$load_state" && "$load_state" != "not-found" ]]
}

detect_pause_units() {
  PAUSE_UNITS=()
  [[ "$PLATFORM" != "macos" ]] || return 0

  # Fixed positive list. Stop order is front-to-back; restart order is reversed
  # so gateways stop before their backend and backends start before gateways.
  local unit
  for unit in \
    "$CLASSIC_WORKER_UNIT" \
    "kienzlefon-ai-asr.service" \
    "kienzlefon-ai-asr-backend.service"; do
    if systemd_unit_exists "$unit"; then
      PAUSE_UNITS+=("$unit")
    fi
  done

  if (( ${#PAUSE_UNITS[@]} == 0 )); then
    warn "No positively listed Kienzlefon ASR unit detected; generation cannot release ASR memory automatically on this host."
  else
    log "ASR units configured for temporary generation pause: $(pause_units_csv)"
  fi
}

pause_units_csv() {
  local result="" unit
  if (( ${#PAUSE_UNITS[@]} > 0 )); then
    for unit in "${PAUSE_UNITS[@]}"; do
      [[ -z "$result" ]] || result+=","
      result+="$unit"
    done
  fi
  printf '%s\n' "$result"
}

install_source() {
  if [[ -d "${SRC_DIR}/.git" ]]; then
    [[ -z "$(git -C "$SRC_DIR" status --porcelain --untracked-files=no)" ]] \
      || die "Local changes in ${SRC_DIR}; refusing to overwrite them."
    git -C "$SRC_DIR" remote set-url origin "$REPO_URL"
    git -C "$SRC_DIR" fetch --tags --force origin
  elif [[ -e "$SRC_DIR" ]]; then
    die "${SRC_DIR} exists but is not a git checkout. Refusing to overwrite it."
  else
    log "Cloning pinned qwen3-tts source..."
    git clone --recursive "$REPO_URL" "$SRC_DIR"
  fi
  git -C "$SRC_DIR" checkout --detach "$REPO_COMMIT"
  git -C "$SRC_DIR" submodule update --init --recursive
  [[ "$(git -C "$SRC_DIR" rev-parse HEAD)" == "$REPO_COMMIT" ]] \
    || die "Pinned qwen3-tts revision was not activated."
  [[ -f "${SRC_DIR}/Makefile" ]] || die "Source checkout is missing Makefile"
  [[ -x "${SRC_DIR}/download_model.sh" ]] || chmod +x "${SRC_DIR}/download_model.sh"
  log "qwen3-tts source pinned: ${REPO_COMMIT}"
}

build_binary() {
  if [[ "$PLATFORM" == "macos" ]]; then
    log "Building Metal-capable native binary (CPU remains runtime default on macOS)..."
    (
      cd "$SRC_DIR"
      make metal CC=clang
    )
  else
    log "Building CUDA-capable native binary for ${CUDA_ARCH} (CUDA will be runtime default on Ubuntu)..."
    (
      cd "$SRC_DIR"
      make cuda CUDA_HOME="$CUDA_HOME" NVCC_ARCH="-arch=${CUDA_ARCH}"
    )
  fi

  [[ -x "${SRC_DIR}/qwen_tts" ]] || die "Build completed without producing ${SRC_DIR}/qwen_tts"
  install -m 0755 "${SRC_DIR}/qwen_tts" "$BINARY"

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    # A CUDA build links CUDA shared libraries even when the CPU backend is used.
    # Verify the installed binary can resolve every dependency. The env file and
    # systemd unit also carry CUDA_LIBDIR for non-standard toolkit prefixes.
    if ! LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ldd "$BINARY" | grep -q 'not found'; then
      :
    else
      LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ldd "$BINARY" >&2 || true
      die "The CUDA-capable qwen_tts binary has unresolved shared libraries."
    fi
  fi

  run_binary --caps >/dev/null 2>&1 || warn "qwen_tts --caps returned non-zero; continuing to functional tests."
  run_binary --self-test >/dev/null 2>&1 || die "qwen_tts --self-test failed"
}

cpu_binary_is_usable() {
  [[ -x "$CPU_BINARY" ]] || return 1
  "$CPU_BINARY" --self-test >/dev/null 2>&1 || return 1
  if [[ "$PLATFORM" != "macos" ]] && ldd "$CPU_BINARY" 2>/dev/null | grep -Eq 'libcuda|libcudart|libcublas'; then
    return 1
  fi
  return 0
}

build_offline_cpu_binary() {
  if cpu_binary_is_usable; then
    log "Existing independent CPU binary passed self-test; no rebuild needed."
    return 0
  fi

  local build_root build_src
  build_root="$(mktemp -d /tmp/kienzlefon-qwen-cpu-build.XXXXXX)"
  build_src="${build_root}/src"
  CLEANUP_TMP="$build_root"

  log "Building independent CPU-only BLAS binary in a temporary build tree..."
  cp -R "$SRC_DIR" "$build_src"

  if [[ "$PLATFORM" == "macos" ]]; then
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas CC=clang
    )
  elif grep -qw avx2 /proc/cpuinfo && grep -qw fma /proc/cpuinfo; then
    log "CPU supports AVX2 and FMA; using the normal x86 BLAS build."
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas
    )
  else
    warn "CPU lacks AVX2/FMA; building the slower scalar fallback."
    (
      cd "$build_src"
      make clean >/dev/null 2>&1 || true
      make blas SIMD=scalar
    )
  fi

  [[ -x "${build_src}/qwen_tts" ]] || die "CPU build completed without producing qwen_tts"
  install -m 0755 "${build_src}/qwen_tts" "$CPU_BINARY"

  if [[ "$PLATFORM" != "macos" ]]; then
    if ldd "$CPU_BINARY" | grep -q 'not found'; then
      ldd "$CPU_BINARY" >&2 || true
      die "The CPU-only qwen_tts binary has unresolved shared libraries."
    fi
    if ldd "$CPU_BINARY" | grep -Eq 'libcuda|libcudart|libcublas'; then
      die "The supposed CPU-only qwen_tts binary unexpectedly depends on CUDA libraries."
    fi
  fi

  "$CPU_BINARY" --caps >/dev/null 2>&1 || warn "CPU qwen_tts --caps returned non-zero; continuing to self-test."
  "$CPU_BINARY" --self-test >/dev/null 2>&1 || die "CPU-only qwen_tts --self-test failed"

  rm -rf -- "$build_root"
  CLEANUP_TMP=""
}

cuda_binary_is_usable() {
  [[ "$PLATFORM" != "macos" && "$CUDA_AVAILABLE" -eq 1 && -x "$CUDA_BINARY" ]] || return 1
  if LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
      ldd "$CUDA_BINARY" 2>/dev/null | grep -q 'not found'; then
    return 1
  fi
  LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
    "$CUDA_BINARY" --self-test >/dev/null 2>&1 || return 1
  return 0
}

build_offline_cuda_binary() {
  [[ "$PLATFORM" != "macos" && "$CUDA_AVAILABLE" -eq 1 ]] || return 0

  if cuda_binary_is_usable; then
    log "Existing independent CUDA binary passed dependency/basic self-test; runtime GPU test follows after ASR stop."
    return 0
  fi

  local build_root build_src
  build_root="$(mktemp -d /tmp/kienzlefon-qwen-cuda-build.XXXXXX)"
  build_src="${build_root}/src"
  CLEANUP_TMP="$build_root"

  log "Building independent CUDA binary for ${CUDA_ARCH} in a temporary build tree..."
  cp -R "$SRC_DIR" "$build_src"
  if ! (
    cd "$build_src"
    make clean >/dev/null 2>&1 || true
    make cuda CUDA_HOME="$CUDA_HOME" NVCC_ARCH="-arch=${CUDA_ARCH}"
  ); then
    warn "CUDA build failed; keeping the required CPU generator as fallback."
    rm -rf -- "$build_root"
    rm -f -- "$CUDA_BINARY"
    CLEANUP_TMP=""
    CUDA_AVAILABLE=0
    return 0
  fi

  if [[ ! -x "${build_src}/qwen_tts" ]]; then
    warn "CUDA build produced no executable; keeping the CPU generator as fallback."
    rm -rf -- "$build_root"
    rm -f -- "$CUDA_BINARY"
    CLEANUP_TMP=""
    CUDA_AVAILABLE=0
    return 0
  fi

  install -m 0755 "${build_src}/qwen_tts" "$CUDA_BINARY"
  rm -rf -- "$build_root"
  CLEANUP_TMP=""

  if ! cuda_binary_is_usable; then
    warn "CUDA binary failed dependency or basic self-test; offline generation will use CPU."
    rm -f -- "$CUDA_BINARY"
    CUDA_AVAILABLE=0
    return 0
  fi

  log "Independent CUDA binary passed dependency/basic self-test; runtime GPU test follows after ASR stop."
}

run_binary() {
  if [[ "$PLATFORM" == "ubuntu" ]]; then
    LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" "$BINARY" "$@"
  else
    "$BINARY" "$@"
  fi
}

download_model() {
  if model_is_complete "$MODEL_DIR"; then
    log "Complete 0.6B CustomVoice model already present; no download needed."
    return
  fi

  if [[ -e "$MODEL_DIR" ]]; then
    warn "Model directory exists but is incomplete. It will not be trusted or modified in place."
    mv "$MODEL_DIR" "${MODEL_DIR}.incomplete.$(date '+%Y%m%d-%H%M%S')"
  fi

  local stage="${MODEL_BASE}/.qwen3-tts-0.6b-customvoice.download.$$"
  rm -rf -- "$stage"
  mkdir -p "$stage"
  CLEANUP_STAGE="$stage"

  log "Downloading ${MODEL_HF_ID} into staging directory..."
  (
    cd "$SRC_DIR"
    ./download_model.sh --model small --dir "$stage"
  )

  model_is_complete "$stage" || die "Downloaded model failed completeness validation"
  mv "$stage" "$MODEL_DIR"
  CLEANUP_STAGE=""
  touch "${MODEL_DIR}/.kienzlefon-complete"
  log "Model download complete."
}

write_env_file() {
  cat > "$ENV_FILE" <<EOF_ENV
# Generated by ${SCRIPT_NAME}
KIENZLEFON_QWEN_PLATFORM=${PLATFORM}
KIENZLEFON_QWEN_PORT=${PORT}
KIENZLEFON_QWEN_THREADS=${THREADS}
KIENZLEFON_QWEN_BATCH_SIZE=${BATCH_SIZE}
KIENZLEFON_QWEN_DEFAULT_BACKEND=$([[ "$PLATFORM" == "ubuntu" ]] && echo cuda || echo cpu)
KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int8
KIENZLEFON_QWEN_MODEL=${MODEL_DIR}
CUDA_HOME=${CUDA_HOME}
CUDA_LIBDIR=${CUDA_LIBDIR}
CUDA_ARCH=${CUDA_ARCH}
EOF_ENV
  chmod 0644 "$ENV_FILE"
}

write_offline_env_file() {
  cat > "$OFFLINE_ENV_FILE" <<EOF_OFFLINE_ENV
# Generated by ${SCRIPT_NAME}
KIENZLEFON_QWEN_INSTALL_MODE=offline-one-shot
KIENZLEFON_QWEN_PLATFORM=${PLATFORM}
KIENZLEFON_QWEN_THREADS=${THREADS}
KIENZLEFON_QWEN_MODEL=${MODEL_DIR}
KIENZLEFON_QWEN_CPU_BINARY=${CPU_BINARY}
KIENZLEFON_QWEN_CUDA_BINARY=${CUDA_BINARY}
KIENZLEFON_QWEN_CUDA_AVAILABLE=${CUDA_AVAILABLE}
KIENZLEFON_QWEN_BACKEND_PREFERENCE=$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)
KIENZLEFON_QWEN_DEFAULT_QUANTIZATION=int8
KIENZLEFON_QWEN_OUTPUT_FORMAT=wav-pcm-s16le-24000hz-mono
KIENZLEFON_QWEN_PAUSE_UNITS=$(pause_units_csv)
KIENZLEFON_QWEN_MAINTENANCE_MARKER=${MAINTENANCE_MARKER}
KIENZLEFON_QWEN_MIN_AVAILABLE_KIB=${MIN_GENERATE_AVAILABLE_KIB}
KIENZLEFON_QWEN_STOP_TIMEOUT_SECONDS=${STOP_TIMEOUT_SECONDS}
KIENZLEFON_QWEN_READINESS_TIMEOUT_SECONDS=${READINESS_TIMEOUT_SECONDS}
CUDA_HOME=${CUDA_HOME}
CUDA_LIBDIR=${CUDA_LIBDIR}
CUDA_ARCH=${CUDA_ARCH}
EOF_OFFLINE_ENV
  chmod 0644 "$OFFLINE_ENV_FILE"
}

install_generate_command() {
  local pause_units_literal="" unit
  if (( ${#PAUSE_UNITS[@]} > 0 )); then
    for unit in "${PAUSE_UNITS[@]}"; do
      [[ "$unit" =~ ^[A-Za-z0-9_.@:-]+\.service$ ]] || die "Unsafe ASR unit name refused: ${unit}"
      printf -v pause_units_literal '%s  %q\n' "$pause_units_literal" "$unit"
    done
  fi

  cat > "$GENERATE_CMD" <<EOF_GENERATE
#!/bin/bash
# Non-resident Kienzlefon Qwen3-TTS announcement generator.
set -Eeuo pipefail
IFS=\$'\\n\\t'
umask 022

PLATFORM="${PLATFORM}"
CPU_BIN="${CPU_BINARY}"
CUDA_BIN="${CUDA_BINARY}"
CUDA_ENABLED="${CUDA_AVAILABLE}"
CUDA_LIBDIR="${CUDA_LIBDIR}"
MODEL="${MODEL_DIR}"
THREADS="${THREADS}"
LOCK_FILE="${GENERATE_LOCK}"
MIN_AVAILABLE_KIB="${MIN_GENERATE_AVAILABLE_KIB}"
STOP_TIMEOUT="${STOP_TIMEOUT_SECONDS}"
READINESS_TIMEOUT="${READINESS_TIMEOUT_SECONDS}"
MAINTENANCE_MARKER="${MAINTENANCE_MARKER}"
CLASSIC_WORKER_UNIT="${CLASSIC_WORKER_UNIT}"
CLASSIC_STATUS_CMD="${CLASSIC_STATUS_CMD}"
CLASSIC_STATUS_PYTHON="${CLASSIC_STATUS_PYTHON}"
CLASSIC_CONFIG="${CLASSIC_CONFIG}"
CLASSIC_HEARTBEAT="${CLASSIC_HEARTBEAT}"
PAUSE_UNITS=(
${pause_units_literal})

TEXT=""
OUTPUT=""
SPEAKER="uncle_fu"
LANGUAGE="German"
SEED="${TEST_SEED}"
FORCE=0
TMP_OUTPUT=""
TMP_DIR=""
CUDA_LOG=""
CPU_LOG=""
LOCK_DIR=""
LOCK_CANDIDATE=""
MARKER_CREATED=0
MARKER_TMP=""
KEEP_MARKER=0
RESTORE_REQUIRED=0
RESTORE_COMPLETE=0
OLD_HEARTBEAT_PID=""
OLD_HEARTBEAT_UPDATED=""
ACTIVE_BEFORE=()
TARGET_UID=""
TARGET_GID=""

usage() {
  cat <<'USAGE'
Usage:
  kienzlefon-qwen3-tts-generate --text TEXT --output FILE.wav [options]

Required:
  --text TEXT           Text to synthesize
  --output FILE.wav     Destination WAV (PCM S16LE, 24000 Hz, mono)

Optional:
  --speaker NAME        CustomVoice speaker (default: uncle_fu)
  --language LANGUAGE   Language (default: German)
  --seed N              Non-negative deterministic seed (default: 42)
  --force               Atomically replace an existing destination file
  -h, --help            Show this help

The command prefers a validated CUDA backend when installed and usable, then
automatically retries once with the independent CPU binary. Before model loading,
it temporarily stops only positively listed Kienzlefon ASR units that were active.
It restores and verifies them before activating the finished WAV. It starts no
HTTP server, opens no TCP port, and exits after writing the WAV file.
USAGE
}

die() {
  printf '[ERROR] %s\\n' "\$*" >&2
  exit 1
}

unit_is_active() {
  systemctl is-active --quiet "\$1" 2>/dev/null
}

classic_worker_was_active() {
  local i
  for i in "\${!PAUSE_UNITS[@]}"; do
    if [[ "\${PAUSE_UNITS[\$i]}" == "\$CLASSIC_WORKER_UNIT" && "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]]; then
      return 0
    fi
  done
  return 1
}

create_maintenance_marker() {
  (( \${#PAUSE_UNITS[@]} > 0 )) || return 0
  mkdir -p "\$(dirname "\$MAINTENANCE_MARKER")"
  if [[ -e "\$MAINTENANCE_MARKER" ]]; then
    die "ASR maintenance marker already exists; refusing concurrent generation: \$MAINTENANCE_MARKER"
  fi
  MARKER_TMP="\$(mktemp "\${MAINTENANCE_MARKER}.tmp.XXXXXX")"
  printf 'qwen3-tts-generation pid=%s started=%s\\n' "\$\$" "\$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >"\$MARKER_TMP"
  chmod 0644 "\$MARKER_TMP"
  mv -f -- "\$MARKER_TMP" "\$MAINTENANCE_MARKER"
  MARKER_TMP=""
  MARKER_CREATED=1
}

remove_owned_maintenance_marker() {
  if [[ "\$MARKER_CREATED" -eq 1 && "\$KEEP_MARKER" -eq 0 ]]; then
    rm -f -- "\$MAINTENANCE_MARKER"
    MARKER_CREATED=0
  fi
}

read_old_heartbeat_identity() {
  [[ -x "\$CLASSIC_STATUS_PYTHON" && -r "\$CLASSIC_HEARTBEAT" ]] || return 0
  local identity old_ifs
  identity="\$("\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        value = json.load(handle)
    print("{}|{}".format(value.get("pid", -1), value.get("updated_at", "?")))
except Exception:
    print("-1|?")
' "\$CLASSIC_HEARTBEAT" 2>/dev/null || printf '%s' '-1|?')"
  old_ifs="\$IFS"
  IFS='|' read -r OLD_HEARTBEAT_PID OLD_HEARTBEAT_UPDATED <<<"\$identity"
  IFS="\$old_ifs"
}

check_classic_worker_idle() {
  classic_worker_was_active || return 0
  [[ -x "\$CLASSIC_STATUS_CMD" ]] || die "Classic status command is missing: \$CLASSIC_STATUS_CMD"
  [[ -x "\$CLASSIC_STATUS_PYTHON" ]] || die "Classic status Python is missing: \$CLASSIC_STATUS_PYTHON"
  [[ -r "\$CLASSIC_CONFIG" ]] || die "Classic Kienzlefon config is missing: \$CLASSIC_CONFIG"

  local status_json counts recording processing queue old_ifs
  if ! status_json="\$("\$CLASSIC_STATUS_CMD" --config "\$CLASSIC_CONFIG" 2>/dev/null)"; then
    die "Classic Whisper worker is not ready before generation; refusing to stop it"
  fi
  counts="\$("\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
value = json.load(sys.stdin)
calls = value.get("calls", {})
print("{}:{}:{}".format(
    int(calls.get("recording", 0)),
    int(calls.get("processing", 0)),
    int(calls.get("queue", 0)),
))
' <<<"\$status_json")" || die "Could not parse classic Kienzlefon status JSON"
  old_ifs="\$IFS"
  IFS=':' read -r recording processing queue <<<"\$counts"
  IFS="\$old_ifs"
  [[ "\$recording" -eq 0 ]] || die "Kienzlefon currently has \$recording active recording(s); generation was not started"
  [[ "\$processing" -eq 0 ]] || die "Kienzlefon currently processes \$processing ASR job(s); generation was not started"
  printf '[INFO] Classic Kienzlefon is idle; queued jobs left in place: %s\\n' "\$queue"
  read_old_heartbeat_identity
}

record_active_units() {
  local i unit active_count=0
  ACTIVE_BEFORE=()
  for i in "\${!PAUSE_UNITS[@]}"; do
    unit="\${PAUSE_UNITS[\$i]}"
    if unit_is_active "\$unit"; then
      ACTIVE_BEFORE[\$i]=1
      active_count=\$((active_count + 1))
    else
      ACTIVE_BEFORE[\$i]=0
    fi
  done
  printf '[INFO] Active ASR units to restore later: %s\\n' "\$active_count"
}

wait_units_stopped() {
  local waited i unit pid all_stopped
  for ((waited=0; waited<STOP_TIMEOUT; waited++)); do
    all_stopped=1
    for i in "\${!PAUSE_UNITS[@]}"; do
      [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
      unit="\${PAUSE_UNITS[\$i]}"
      pid="\$(systemctl show "\$unit" -p MainPID --value 2>/dev/null || printf '0')"
      if unit_is_active "\$unit" || [[ "\${pid:-0}" != "0" ]]; then
        all_stopped=0
        break
      fi
    done
    (( all_stopped == 1 )) && return 0
    sleep 1
  done
  return 1
}

stop_active_units() {
  local i unit
  RESTORE_REQUIRED=1
  for i in "\${!PAUSE_UNITS[@]}"; do
    [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
    unit="\${PAUSE_UNITS[\$i]}"
    printf '[INFO] Stopping ASR unit: %s\\n' "\$unit"
    systemctl --no-block stop "\$unit" || return 1
  done
  wait_units_stopped
}

check_available_memory() {
  [[ "\$PLATFORM" != "macos" ]] || return 0
  local available_kib
  available_kib="\$(awk '/^MemAvailable:/ {print \$2}' /proc/meminfo)"
  case "\$available_kib" in ''|*[!0-9]*) die "Could not read MemAvailable from /proc/meminfo" ;; esac
  printf '[INFO] Memory available after ASR stop: %s MiB\\n' "\$((available_kib / 1024))"
  (( available_kib >= MIN_AVAILABLE_KIB )) \
    || die "Only \$((available_kib / 1024)) MiB available after ASR stop; at least \$((MIN_AVAILABLE_KIB / 1024)) MiB required"
}

current_heartbeat_identity() {
  "\$CLASSIC_STATUS_PYTHON" -c '
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("ready") is not True:
        raise ValueError("not ready")
    print("{}|{}".format(int(value.get("pid", -1)), value.get("updated_at", "?")))
except Exception:
    raise SystemExit(1)
' "\$CLASSIC_HEARTBEAT" 2>/dev/null
}

wait_classic_readiness() {
  classic_worker_was_active || return 0
  local waited main_pid identity heartbeat_pid heartbeat_updated old_ifs
  for ((waited=0; waited<READINESS_TIMEOUT; waited++)); do
    if unit_is_active "\$CLASSIC_WORKER_UNIT" \
        && "\$CLASSIC_STATUS_CMD" --config "\$CLASSIC_CONFIG" >/dev/null 2>&1; then
      main_pid="\$(systemctl show "\$CLASSIC_WORKER_UNIT" -p MainPID --value 2>/dev/null || printf '0')"
      identity="\$(current_heartbeat_identity 2>/dev/null || true)"
      old_ifs="\$IFS"
      IFS='|' read -r heartbeat_pid heartbeat_updated <<<"\$identity"
      IFS="\$old_ifs"
      if [[ -n "\$identity" && "\$main_pid" != "0" && "\$heartbeat_pid" == "\$main_pid" \
          && "\$heartbeat_updated" != "\$OLD_HEARTBEAT_UPDATED" ]]; then
        printf '[INFO] Classic Whisper worker is ready with new heartbeat PID %s.\\n' "\$main_pid"
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

restore_paused_units() {
  if (( RESTORE_REQUIRED == 0 )); then
    RESTORE_COMPLETE=1
    return 0
  fi

  local i unit waited all_active=0
  for ((i=\${#PAUSE_UNITS[@]}-1; i>=0; i--)); do
    [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
    unit="\${PAUSE_UNITS[\$i]}"
    printf '[INFO] Starting previously active ASR unit: %s\\n' "\$unit"
    systemctl --no-block start "\$unit" || return 1
  done

  for ((waited=0; waited<READINESS_TIMEOUT; waited++)); do
    all_active=1
    for i in "\${!PAUSE_UNITS[@]}"; do
      [[ "\${ACTIVE_BEFORE[\$i]:-0}" -eq 1 ]] || continue
      unit_is_active "\${PAUSE_UNITS[\$i]}" || { all_active=0; break; }
    done
    (( all_active == 1 )) && break
    sleep 1
  done
  (( all_active == 1 )) || return 1
  wait_classic_readiness || return 1
  RESTORE_COMPLETE=1
  return 0
}

prepare_generation_resources() {
  (( \${#PAUSE_UNITS[@]} == 0 )) || [[ "\${EUID}" -eq 0 ]] \
    || die "Root privileges are required to pause configured ASR units"
  if (( \${#PAUSE_UNITS[@]} > 0 )); then
    command -v systemctl >/dev/null 2>&1 || die "systemctl is required for configured ASR units"
    record_active_units
    create_maintenance_marker
    check_classic_worker_idle
    if ! stop_active_units; then
      die "Configured ASR units did not stop cleanly within \${STOP_TIMEOUT} seconds"
    fi
  fi
  check_available_memory
}

cleanup() {
  local rc=\$?
  set +e
  if [[ "\$RESTORE_REQUIRED" -eq 1 && "\$RESTORE_COMPLETE" -eq 0 ]]; then
    printf '[WARN] Restoring ASR units after interrupted or failed generation.\\n' >&2
    if ! restore_paused_units; then
      KEEP_MARKER=1
      printf '[CRITICAL] ASR units could not be restored; maintenance marker remains at %s\\n' "\$MAINTENANCE_MARKER" >&2
    fi
  fi
  if [[ "\$KEEP_MARKER" -eq 0 ]]; then remove_owned_maintenance_marker; fi
  [[ -n "\$MARKER_TMP" ]] && rm -f -- "\$MARKER_TMP"
  [[ -n "\$TMP_OUTPUT" ]] && rm -f -- "\$TMP_OUTPUT"
  [[ -n "\$CUDA_LOG" ]] && rm -f -- "\$CUDA_LOG"
  [[ -n "\$CPU_LOG" ]] && rm -f -- "\$CPU_LOG"
  [[ -n "\$TMP_DIR" ]] && rmdir "\$TMP_DIR" >/dev/null 2>&1
  [[ -n "\$LOCK_DIR" ]] && rmdir "\$LOCK_DIR" >/dev/null 2>&1
  return "\$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [[ \$# -gt 0 ]]; do
  case "\$1" in
    --text)
      [[ \$# -ge 2 ]] || die "--text requires a value"
      TEXT="\$2"; shift 2 ;;
    --output)
      [[ \$# -ge 2 ]] || die "--output requires a value"
      OUTPUT="\$2"; shift 2 ;;
    --speaker)
      [[ \$# -ge 2 ]] || die "--speaker requires a value"
      SPEAKER="\$2"; shift 2 ;;
    --language)
      [[ \$# -ge 2 ]] || die "--language requires a value"
      LANGUAGE="\$2"; shift 2 ;;
    --seed)
      [[ \$# -ge 2 ]] || die "--seed requires a value"
      SEED="\$2"; shift 2 ;;
    --force)
      FORCE=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      die "Unknown option: \$1" ;;
  esac
done

[[ -n "\$TEXT" ]] || die "--text is required and must not be empty"
[[ -n "\$OUTPUT" ]] || die "--output is required"
[[ -n "\$SPEAKER" ]] || die "--speaker must not be empty"
[[ -n "\$LANGUAGE" ]] || die "--language must not be empty"
case "\$SEED" in ''|*[!0-9]*) die "--seed must be a non-negative integer" ;; esac
case "\$OUTPUT" in *.wav|*.WAV) ;; *) die "--output must end in .wav" ;; esac

[[ -x "\$CPU_BIN" ]] || die "CPU generator binary is missing: \$CPU_BIN"
[[ -d "\$MODEL" ]] || die "Qwen3-TTS model directory is missing: \$MODEL"

OUTPUT_DIR="\$(dirname "\$OUTPUT")"
[[ -d "\$OUTPUT_DIR" ]] || die "Output directory does not exist: \$OUTPUT_DIR"
[[ -w "\$OUTPUT_DIR" ]] || die "Output directory is not writable: \$OUTPUT_DIR"
if [[ -e "\$OUTPUT" && "\$FORCE" -eq 0 ]]; then
  die "Output already exists; use --force to replace it: \$OUTPUT"
fi
if [[ "\${EUID}" -eq 0 ]]; then
  owner_source="\$OUTPUT_DIR"
  [[ -e "\$OUTPUT" ]] && owner_source="\$OUTPUT"
  if [[ "\$PLATFORM" == "macos" ]]; then
    TARGET_UID="\$(stat -f '%u' "\$owner_source")"
    TARGET_GID="\$(stat -f '%g' "\$owner_source")"
  else
    TARGET_UID="\$(stat -c '%u' "\$owner_source")"
    TARGET_GID="\$(stat -c '%g' "\$owner_source")"
  fi
fi

# Serialize generation so multiple model instances cannot exhaust RAM/VRAM.
if command -v flock >/dev/null 2>&1; then
  exec 9>>"\$LOCK_FILE"
  flock -n 9 || die "Another Qwen3-TTS generation is already running"
else
  LOCK_CANDIDATE="/tmp/kienzlefon-qwen3-tts-generate.lock.d"
  if mkdir "\$LOCK_CANDIDATE" 2>/dev/null; then
    LOCK_DIR="\$LOCK_CANDIDATE"
  else
    die "Another Qwen3-TTS generation is already running"
  fi
fi

# The temporary directory is inside the destination directory: the final rename
# is atomic and the native output path still has a real .wav suffix.
TMP_DIR="\$(mktemp -d "\${OUTPUT_DIR}/.kienzlefon-qwen3-tts.XXXXXX")"
TMP_OUTPUT="\${TMP_DIR}/output.wav"
CUDA_LOG="\${TMP_DIR}/cuda.log"
CPU_LOG="\${TMP_DIR}/cpu.log"

prepare_generation_resources

byte_at() {
  od -An -tu1 -j "\$2" -N1 "\$1" | tr -d '[:space:]'
}

u16le_at() {
  local b0 b1
  b0="\$(byte_at "\$1" "\$2")"
  b1="\$(byte_at "\$1" "\$((\$2 + 1))")"
  printf '%s\\n' "\$((b0 + (b1 << 8)))"
}

u32le_at() {
  local b0 b1 b2 b3
  b0="\$(byte_at "\$1" "\$2")"
  b1="\$(byte_at "\$1" "\$((\$2 + 1))")"
  b2="\$(byte_at "\$1" "\$((\$2 + 2))")"
  b3="\$(byte_at "\$1" "\$((\$2 + 3))")"
  printf '%s\\n' "\$((b0 + (b1 << 8) + (b2 << 16) + (b3 << 24)))"
}

validate_qwen_wav() {
  local f="\$1" size
  [[ -s "\$f" ]] || return 1
  size="\$(wc -c < "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
  [[ "\$(u16le_at "\$f" 20)" -eq 1 ]] || return 1
  [[ "\$(u16le_at "\$f" 22)" -eq 1 ]] || return 1
  [[ "\$(u32le_at "\$f" 24)" -eq 24000 ]] || return 1
  [[ "\$(u16le_at "\$f" 34)" -eq 16 ]] || return 1
}

run_cpu() {
  rm -f -- "\$TMP_OUTPUT"
  "\$CPU_BIN" -d "\$MODEL" --int8 -j "\$THREADS" \
    -s "\$SPEAKER" -l "\$LANGUAGE" --seed "\$SEED" \
    --text "\$TEXT" -o "\$TMP_OUTPUT" >"\$CPU_LOG" 2>&1
}

run_cuda() {
  rm -f -- "\$TMP_OUTPUT"
  QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
    LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}" \
    "\$CUDA_BIN" -d "\$MODEL" --int8 -j "\$THREADS" --backend cuda \
    -s "\$SPEAKER" -l "\$LANGUAGE" --seed "\$SEED" \
    --text "\$TEXT" -o "\$TMP_OUTPUT" >"\$CUDA_LOG" 2>&1
}

BACKEND="cpu"
CUDA_OK=0
if [[ "\$PLATFORM" != "macos" && "\$CUDA_ENABLED" -eq 1 && -x "\$CUDA_BIN" ]] \
    && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  if LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}" \
      "\$CUDA_BIN" --gpu-selftest --backend cuda >"\$CUDA_LOG" 2>&1; then
    if run_cuda && validate_qwen_wav "\$TMP_OUTPUT"; then
      CUDA_OK=1
      BACKEND="cuda"
    else
      printf '[WARN] CUDA generation failed; retrying once with CPU.\\n' >&2
    fi
  else
    printf '[WARN] CUDA self-test failed; using CPU.\\n' >&2
  fi
fi

if [[ "\$CUDA_OK" -eq 0 ]]; then
  if ! run_cpu; then
    die "Qwen3-TTS CPU generation failed (input text was not logged)"
  fi
  validate_qwen_wav "\$TMP_OUTPUT" || die "Generator produced no valid PCM S16LE/24000 Hz/mono WAV"
fi

if ! restore_paused_units; then
  KEEP_MARKER=1
  die "Previously active ASR units failed to return to their verified ready state; generated audio was not activated"
fi

if [[ -e "\$OUTPUT" && "\$FORCE" -eq 0 ]]; then
  die "Output appeared during generation; refusing to overwrite it without --force"
fi
chmod 0644 "\$TMP_OUTPUT"
if [[ "\${EUID}" -eq 0 && -n "\$TARGET_UID" && -n "\$TARGET_GID" ]]; then
  chown "\${TARGET_UID}:\${TARGET_GID}" "\$TMP_OUTPUT"
fi
mv -f -- "\$TMP_OUTPUT" "\$OUTPUT"
TMP_OUTPUT=""
printf 'Generated WAV: %s (backend=%s, PCM S16LE, 24000 Hz, mono)\\n' "\$OUTPUT" "\$BACKEND"
EOF_GENERATE

  chmod 0755 "$GENERATE_CMD"
  touch "$GENERATE_LOCK"
  chmod 0666 "$GENERATE_LOCK"
}

offline_smoke_tests() {
  local tmp
  tmp="$(mktemp -d /tmp/kienzlefon-qwen-offline-test.XXXXXX)"
  CLEANUP_TMP="$tmp"

  log "Running full offline generation test, including configured ASR stop and verified restoration..."
  "$GENERATE_CMD" \
    --text "Dies ist ein technischer Installationstest." \
    --output "${tmp}/installation-test.wav"
  validate_wav "${tmp}/installation-test.wav" || die "Full offline generation test produced an invalid WAV"

  rm -rf -- "$tmp"
  CLEANUP_TMP=""
}

install_ttfa_helper() {
  local src="${TOOLS_DIR}/kienzlefon_qwen_ttfa.c"
  cat > "$src" <<'C_EOF'
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static double now_sec(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static int send_all(int fd, const char *buf, size_t len) {
    while (len > 0) {
        ssize_t n = send(fd, buf, len, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        buf += (size_t)n;
        len -= (size_t)n;
    }
    return 0;
}

static char *find_bytes(char *buf, size_t len, const char *needle, size_t nlen) {
    if (nlen == 0 || len < nlen) return NULL;
    for (size_t i = 0; i + nlen <= len; i++) {
        if (memcmp(buf + i, needle, nlen) == 0) return buf + i;
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: %s <ipv4> <port> <path> <json-body>\n", argv[0]);
        return 2;
    }

    signal(SIGPIPE, SIG_IGN);

    const char *host = argv[1];
    int port = atoi(argv[2]);
    const char *path = argv[3];
    const char *body = argv[4];
    if (port < 1 || port > 65535) {
        fprintf(stderr, "invalid port\n");
        return 2;
    }

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return 2; }

    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((unsigned short)port);
    if (inet_pton(AF_INET, host, &sa.sin_addr) != 1) {
        fprintf(stderr, "host must be an IPv4 address\n");
        close(fd);
        return 2;
    }

    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) != 0) {
        perror("connect");
        close(fd);
        return 2;
    }

    size_t body_len = strlen(body);
    size_t req_cap = body_len + strlen(path) + 512;
    char *req = malloc(req_cap);
    if (!req) { close(fd); return 2; }
    int req_len = snprintf(req, req_cap,
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n\r\n%s",
        path, host, port, body_len, body);
    if (req_len < 0 || (size_t)req_len >= req_cap) {
        fprintf(stderr, "request too large\n");
        free(req); close(fd); return 2;
    }

    double t0 = now_sec();
    if (send_all(fd, req, (size_t)req_len) != 0) {
        perror("send");
        free(req); close(fd); return 2;
    }
    free(req);

    size_t cap = 131072, used = 0;
    char *prefix = malloc(cap);
    if (!prefix) { close(fd); return 2; }

    int first_audio_seen = 0;
    double ttfa = -1.0;
    size_t total_received = 0;
    char recvbuf[32768];

    for (;;) {
        ssize_t n = recv(fd, recvbuf, sizeof(recvbuf), 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            perror("recv");
            free(prefix); close(fd); return 2;
        }
        if (n == 0) break;
        total_received += (size_t)n;

        if (!first_audio_seen) {
            if (used + (size_t)n > cap) {
                size_t newcap = cap * 2;
                while (newcap < used + (size_t)n) newcap *= 2;
                if (newcap > 1048576) {
                    fprintf(stderr, "response prefix too large\n");
                    free(prefix); close(fd); return 2;
                }
                char *tmp = realloc(prefix, newcap);
                if (!tmp) { free(prefix); close(fd); return 2; }
                prefix = tmp; cap = newcap;
            }
            memcpy(prefix + used, recvbuf, (size_t)n);
            used += (size_t)n;

            char *hend = find_bytes(prefix, used, "\r\n\r\n", 4);
            if (hend) {
                size_t header_len = (size_t)(hend - prefix) + 4;
                if (used >= 12 && memcmp(prefix, "HTTP/1.1 200", 12) != 0) {
                    fprintf(stderr, "HTTP request did not return 200\n");
                    free(prefix); close(fd); return 2;
                }
                char *chunk_end = find_bytes(prefix + header_len, used - header_len, "\r\n", 2);
                if (chunk_end) {
                    size_t chunk_line_end = (size_t)(chunk_end - prefix) + 2;
                    if (used > chunk_line_end) {
                        first_audio_seen = 1;
                        ttfa = now_sec() - t0;
                    }
                }
            }
        }
    }

    free(prefix);
    close(fd);

    if (!first_audio_seen || ttfa < 0.0 || total_received == 0) {
        fprintf(stderr, "no streaming PCM observed\n");
        return 2;
    }

    printf("%.6f\n", ttfa);
    return 0;
}
C_EOF

  if [[ "$PLATFORM" == "macos" ]]; then
    clang -O2 -Wall -Wextra -Werror "$src" -o "$TTFA_HELPER"
  else
    gcc -O2 -Wall -Wextra -Werror "$src" -o "$TTFA_HELPER"
  fi
  chmod 0755 "$TTFA_HELPER"
}

service_loaded_or_enabled() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl print "system/${LABEL}" >/dev/null 2>&1
  else
    systemctl is-enabled --quiet "$SYSTEMD_UNIT_NAME" 2>/dev/null || systemctl is-active --quiet "$SYSTEMD_UNIT_NAME" 2>/dev/null
  fi
}

service_active() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl print "system/${LABEL}" >/dev/null 2>&1
  else
    systemctl is-active --quiet "$SYSTEMD_UNIT_NAME"
  fi
}

service_stop() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
      launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
      local i
      for ((i=0; i<50; i++)); do
        launchctl print "system/${LABEL}" >/dev/null 2>&1 || break
        sleep 0.2
      done
    fi
  else
    systemctl stop "$SYSTEMD_UNIT_NAME" >/dev/null 2>&1 || true
  fi
}

service_start() {
  if [[ "$SERVICE_KIND" == "launchd" ]]; then
    launchctl enable "system/${LABEL}" >/dev/null 2>&1 || true
    if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
      launchctl kickstart -k "system/${LABEL}"
    else
      launchctl bootstrap system "$PLIST"
    fi
  else
    systemctl daemon-reload
    systemctl enable "$SYSTEMD_UNIT_NAME" >/dev/null
    systemctl restart "$SYSTEMD_UNIT_NAME"
  fi
}

install_control_command() {
  cat > "$CTL_CMD" <<EOF_CTL
#!/bin/bash
set -Eeuo pipefail
PLATFORM="${PLATFORM}"
LABEL="${LABEL}"
PLIST="${PLIST}"
UNIT="${SYSTEMD_UNIT_NAME}"
LOG_DIR="${LOG_DIR}"

need_root() {
  if [[ "\${EUID}" -ne 0 ]]; then
    exec sudo -- "\$0" "\$@"
  fi
}

if [[ "\$PLATFORM" == "macos" ]]; then
  loaded() { launchctl print "system/\${LABEL}" >/dev/null 2>&1; }
  case "\${1:-status}" in
    start)
      need_root "\$@"
      launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
      if loaded; then launchctl kickstart -k "system/\${LABEL}"; else launchctl bootstrap system "\$PLIST"; fi
      ;;
    stop)
      need_root "\$@"
      if loaded; then launchctl bootout "system/\${LABEL}"; fi
      ;;
    restart)
      need_root "\$@"
      if loaded; then launchctl bootout "system/\${LABEL}" >/dev/null 2>&1 || true; fi
      launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
      launchctl bootstrap system "\$PLIST"
      ;;
    status)
      if loaded; then launchctl print "system/\${LABEL}"; else echo "\${LABEL}: not loaded"; exit 3; fi
      ;;
    logs)
      exec tail -n 100 -F "\${LOG_DIR}/server.stdout.log" "\${LOG_DIR}/server.stderr.log"
      ;;
    *) echo "Usage: \$0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
  esac
else
  case "\${1:-status}" in
    start)   need_root "\$@"; systemctl start "\$UNIT" ;;
    stop)    need_root "\$@"; systemctl stop "\$UNIT" ;;
    restart) need_root "\$@"; systemctl restart "\$UNIT" ;;
    status)  systemctl status --no-pager "\$UNIT" ;;
    logs)    exec journalctl -u "\$UNIT" -n 100 -f ;;
    *) echo "Usage: \$0 {start|stop|restart|status|logs}" >&2; exit 2 ;;
  esac
fi
EOF_CTL
  chmod 0755 "$CTL_CMD"
}

install_health_command() {
  cat > "$HEALTH_CMD" <<EOF_HEALTH
#!/bin/bash
set -Eeuo pipefail
PLATFORM="${PLATFORM}"
PORT="${PORT}"
URL="http://127.0.0.1:\${PORT}"
LABEL="${LABEL}"
UNIT="${SYSTEMD_UNIT_NAME}"
TMP="\$(mktemp -d /tmp/kienzlefon-qwen-health.XXXXXX)"
trap 'rm -rf "\$TMP"' EXIT

fail() { echo "[FAIL] \$*" >&2; exit 1; }
ok()   { echo "[ OK ] \$*"; }
file_size() {
  if [[ "\$PLATFORM" == "macos" ]]; then stat -f '%z' "\$1"; else stat -c '%s' "\$1"; fi
}
validate_wav() {
  local f="\$1" size
  [[ -f "\$f" ]] || return 1
  size="\$(file_size "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
}

if [[ "\$PLATFORM" == "macos" ]]; then
  launchctl print "system/\${LABEL}" >/dev/null 2>&1 || fail "launchd service is not loaded"
  ok "launchd service loaded"
else
  systemctl is-active --quiet "\$UNIT" || fail "systemd service is not active"
  ok "systemd service active"
fi

curl -fsS --max-time 10 "\${URL}/v1/health" >"\${TMP}/health.json" || fail "/v1/health"
ok "/v1/health"

BODY='{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"uncle_fu","language":"German","seed":42}'
curl -fsS --max-time 180 -H 'Content-Type: application/json' -d "\$BODY" \
  "\${URL}/v1/tts" -o "\${TMP}/test.wav" || fail "/v1/tts request"
validate_wav "\${TMP}/test.wav" || fail "/v1/tts returned invalid WAV"
ok "German uncle_fu WAV synthesis"

OPENAI='{"input":"Guten Tag. Wie kann ich Ihnen helfen?","voice":"uncle_fu","language":"German","seed":42}'
curl -fsS --max-time 180 -H 'Content-Type: application/json' -d "\$OPENAI" \
  "\${URL}/v1/audio/speech" -o "\${TMP}/openai.wav" || fail "/v1/audio/speech request"
validate_wav "\${TMP}/openai.wav" || fail "/v1/audio/speech returned invalid WAV"
ok "OpenAI-compatible WAV endpoint"

curl -fsSN --max-time 180 -D "\${TMP}/stream.headers" -H 'Content-Type: application/json' -d "\$BODY" \
  "\${URL}/v1/tts/stream" -o "\${TMP}/stream.pcm" || fail "/v1/tts/stream request"
[[ -s "\${TMP}/stream.pcm" ]] || fail "stream contained no PCM"
bytes="\$(file_size "\${TMP}/stream.pcm")"
(( bytes % 2 == 0 )) || fail "stream byte count is not valid s16le"
grep -qi '^Content-Type: audio/pcm' "\${TMP}/stream.headers" || fail "stream Content-Type is not audio/pcm"
grep -qi '^X-Sample-Rate: 24000' "\${TMP}/stream.headers" || fail "stream sample rate is not 24000"
grep -qi '^X-Sample-Format: s16le' "\${TMP}/stream.headers" || fail "stream format is not s16le"
grep -qi '^X-Channels: 1' "\${TMP}/stream.headers" || fail "stream is not mono"
ok "streaming PCM: s16le / 24000 Hz / mono (\${bytes} bytes)"

echo "Qwen3-TTS healthcheck passed."
EOF_HEALTH
  chmod 0755 "$HEALTH_CMD"
}

install_benchmark_command() {
  local gpu_backend gpu_label cuda_env cuda_batch_env plausibility
  if [[ "$PLATFORM" == "macos" ]]; then
    gpu_backend="metal"
    gpu_label="Metal"
    cuda_env=""
    cuda_batch_env=""
    plausibility="Upstream M4 reference only: CPU INT8 ~RTF 0.32; Metal INT8 ~RTF 0.28."
  else
    gpu_backend="cuda"
    gpu_label="CUDA"
    cuda_env="QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1"
    if (( BATCH_SIZE > 1 )); then cuda_batch_env="QWEN_CUDA_BATCH=1"; else cuda_batch_env=""; fi
    plausibility="CUDA results vary strongly by GPU; upstream reports 0.6B ~RTF 0.39 on A100 as one reference point."
  fi

  cat > "$BENCH_CMD" <<EOF_BENCH
#!/bin/bash
# Reproducible Kienzlefon Qwen3-TTS benchmark for ${PLATFORM}.
set -Eeuo pipefail
IFS=\$'\\n\\t'

PLATFORM="${PLATFORM}"
LABEL="${LABEL}"
PLIST="${PLIST}"
UNIT="${SYSTEMD_UNIT_NAME}"
BIN="${BINARY}"
TTFA="${TTFA_HELPER}"
MODEL="${MODEL_DIR}"
PORT="${PORT}"
THREADS="${THREADS}"
BATCH="${BATCH_SIZE}"
CUDA_LIBDIR="${CUDA_LIBDIR}"
GPU_BACKEND="${gpu_backend}"
GPU_LABEL="${gpu_label}"
LOG_DIR="${LOG_DIR}"
TEST_TEXT='${TEST_TEXT}'
SEED='${TEST_SEED}'
URL="http://127.0.0.1:\${PORT}"

if [[ "\${EUID}" -ne 0 ]]; then exec sudo -- "\$0" "\$@"; fi

if [[ "\$PLATFORM" == "ubuntu" && -n "\$CUDA_LIBDIR" ]]; then
  export LD_LIBRARY_PATH="\${CUDA_LIBDIR}\${LD_LIBRARY_PATH:+:\${LD_LIBRARY_PATH}}"
fi

TMP="\$(mktemp -d /tmp/kienzlefon-qwen-bench.XXXXXX)"
RESULTS="\${TMP}/results.tsv"
: >"\$RESULTS"

service_was_active=0
server_pid=""
sampler_pid=""

service_is_active() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl print "system/\${LABEL}" >/dev/null 2>&1
  else
    systemctl is-active --quiet "\$UNIT"
  fi
}
service_stop() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl bootout "system/\${LABEL}" >/dev/null 2>&1 || true
  else
    systemctl stop "\$UNIT" >/dev/null 2>&1 || true
  fi
}
service_restore() {
  if [[ "\$PLATFORM" == "macos" ]]; then
    launchctl enable "system/\${LABEL}" >/dev/null 2>&1 || true
    if launchctl print "system/\${LABEL}" >/dev/null 2>&1; then
      launchctl kickstart -k "system/\${LABEL}" >/dev/null 2>&1 || true
    else
      launchctl bootstrap system "\$PLIST" >/dev/null 2>&1 || true
    fi
  else
    systemctl start "\$UNIT" >/dev/null 2>&1 || true
  fi
}

if service_is_active; then service_was_active=1; fi

cleanup() {
  set +e
  if [[ -n "\$server_pid" ]]; then
    kill "\$server_pid" >/dev/null 2>&1 || true
    wait "\$server_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "\$sampler_pid" ]]; then
    wait "\$sampler_pid" >/dev/null 2>&1 || { kill "\$sampler_pid" >/dev/null 2>&1 || true; }
  fi
  if (( service_was_active == 1 )); then service_restore; fi
  rm -rf "\$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_health() {
  local i
  for ((i=1; i<=180; i++)); do
    curl -fsS --max-time 2 "\${URL}/v1/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

file_size() {
  if [[ "\$PLATFORM" == "macos" ]]; then stat -f '%z' "\$1"; else stat -c '%s' "\$1"; fi
}
validate_wav() {
  local f="\$1" size
  [[ -f "\$f" ]] || return 1
  size="\$(file_size "\$f")"
  (( size > 44 )) || return 1
  [[ "\$(dd if="\$f" bs=1 count=4 2>/dev/null)" == "RIFF" ]] || return 1
  [[ "\$(dd if="\$f" bs=1 skip=8 count=4 2>/dev/null)" == "WAVE" ]] || return 1
}

stop_temp_server() {
  if [[ -n "\$server_pid" ]]; then
    kill "\$server_pid" >/dev/null 2>&1 || true
    wait "\$server_pid" >/dev/null 2>&1 || true
    server_pid=""
  fi
  if [[ -n "\$sampler_pid" ]]; then
    wait "\$sampler_pid" >/dev/null 2>&1 || true
    sampler_pid=""
  fi
}

start_sampler() {
  local pid="\$1" out="\$2"
  (
    max=0
    while kill -0 "\$pid" >/dev/null 2>&1; do
      rss="\$(ps -o rss= -p "\$pid" 2>/dev/null | tr -d ' ')"
      case "\$rss" in ''|*[!0-9]*) ;; *) (( rss > max )) && max="\$rss" ;; esac
      sleep 0.1
    done
    echo "\$max" >"\$out"
  ) &
  sampler_pid=\$!
}

run_mode() {
  local name="\$1" backend="\$2" quant="\$3"
  local wav="\${TMP}/\${name}.wav"
  local slog="\${TMP}/\${name}.server.log"
  local rssfile="\${TMP}/\${name}.rss"
  local body gen_time bytes data_bytes audio_s rtf realtime ttfa_s rss_kb rss_mib

  echo
  echo "=== \${name} ==="

  if [[ "\$backend" == "metal" ]]; then
    QWEN_METAL_FUSED_TALKER=1 "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" \
      --backend metal --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
  elif [[ "\$backend" == "cuda" ]]; then
    if (( BATCH > 1 )); then
      QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 QWEN_CUDA_BATCH=1 \
        "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" --backend cuda \
        --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
    else
      QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
        "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" --backend cuda \
        --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
    fi
  else
    "\$BIN" -d "\$MODEL" "--\${quant}" -j "\$THREADS" \
      --serve "\$PORT" --batch-size "\$BATCH" >"\$slog" 2>&1 &
  fi
  server_pid=\$!
  start_sampler "\$server_pid" "\$rssfile"

  if ! wait_health; then
    echo "Server failed to become healthy. Log:" >&2
    tail -n 80 "\$slog" >&2 || true
    return 1
  fi

  body="{\"text\":\"\${TEST_TEXT}\",\"speaker\":\"uncle_fu\",\"language\":\"German\",\"seed\":\${SEED}}"

  # Non-measured warm-up: compare steady-state resident-server performance.
  curl -fsS --max-time 240 -H 'Content-Type: application/json' -d "\$body" \
    "\${URL}/v1/tts" -o /dev/null

  gen_time="\$(curl -fsS --max-time 240 -H 'Content-Type: application/json' -d "\$body" \
    -o "\$wav" -w '%{time_total}' "\${URL}/v1/tts")"
  validate_wav "\$wav" || { echo "Invalid WAV from \${name}" >&2; return 1; }

  bytes="\$(file_size "\$wav")"
  data_bytes=\$(( bytes - 44 ))
  audio_s="\$(awk -v b="\$data_bytes" 'BEGIN { printf "%.6f", b / 48000.0 }')"
  rtf="\$(awk -v g="\$gen_time" -v a="\$audio_s" 'BEGIN { if (a>0) printf "%.4f", g/a; else print "nan" }')"
  realtime="\$(awk -v r="\$rtf" 'BEGIN { if (r>0) printf "%.3f", 1/r; else print "nan" }')"

  ttfa_s="\$("\$TTFA" 127.0.0.1 "\$PORT" /v1/tts/stream "\$body")"

  stop_temp_server
  rss_kb="\$(cat "\$rssfile" 2>/dev/null || echo 0)"
  case "\$rss_kb" in ''|*[!0-9]*) rss_kb=0 ;; esac
  rss_mib="\$(awk -v k="\$rss_kb" 'BEGIN { printf "%.1f", k/1024.0 }')"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "\$name" "\$audio_s" "\$gen_time" "\$rtf" "\$realtime" "\$ttfa_s" "\$rss_mib" >>"\$RESULTS"

  echo "Audio:      \${audio_s} s"
  echo "Generation: \${gen_time} s"
  echo "RTF:        \${rtf}"
  echo "x realtime: \${realtime}x"
  echo "TTFA:       \${ttfa_s} s"
  echo "Peak RSS:   \${rss_mib} MiB (process RSS; GPU VRAM is not included)"
}

if (( service_was_active == 1 )); then
  service_stop
  for ((i=0; i<50; i++)); do
    service_is_active || break
    sleep 0.2
  done
fi

if lsof -nP -iTCP:"\$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port \${PORT} is still in use; refusing benchmark." >&2
  lsof -nP -iTCP:"\$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

run_mode "cpu-int8" cpu int8
run_mode "cpu-int8" cpu int8
run_mode "${gpu_backend}-int8" "${gpu_backend}" int8
run_mode "${gpu_backend}-int8" "${gpu_backend}" int8

echo
echo "Qwen3-TTS 0.6B benchmark summary"
echo "Text: \${TEST_TEXT}"
echo "Speaker: uncle_fu | Language: German | Seed: \${SEED} | Threads: \${THREADS} | Batch: \${BATCH}"
printf '%-12s %10s %10s %8s %10s %10s %12s\n' "Mode" "Audio(s)" "Gen(s)" "RTF" "xRealtime" "TTFA(s)" "PeakRSS(MiB)"
awk -F '\\t' '{ printf "%-12s %10s %10s %8s %10s %10s %12s\\n", \$1,\$2,\$3,\$4,\$5,\$6,\$7 }' "\$RESULTS"

echo
echo "${plausibility}"
echo "Reference values are informational only and never decide installation success."
EOF_BENCH
  chmod 0755 "$BENCH_CMD"
}

write_service_definition() {
  if [[ "$PLATFORM" == "macos" ]]; then
    log "Installing launchd service (${LABEL})..."
    local tmp
    tmp="$(mktemp /tmp/${LABEL}.plist.XXXXXX)"
    cat > "$tmp" <<EOF_PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BINARY}</string>
    <string>-d</string>
    <string>${MODEL_DIR}</string>
    <string>--int8</string>
    <string>-j</string>
    <string>${THREADS}</string>
    <string>--serve</string>
    <string>${PORT}</string>
    <string>--batch-size</string>
    <string>${BATCH_SIZE}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${BASE_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>${LOG_DIR}/server.stdout.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/server.stderr.log</string>
</dict>
</plist>
EOF_PLIST
    plutil -lint "$tmp" >/dev/null
    service_stop
    install -o root -g wheel -m 0644 "$tmp" "$PLIST"
    rm -f "$tmp"
  else
    log "Installing systemd service (${SYSTEMD_UNIT_NAME}) with CUDA INT8 as default backend..."
    service_stop
    local cuda_batch_env=""
    if (( BATCH_SIZE > 1 )); then
      cuda_batch_env="Environment=QWEN_CUDA_BATCH=1"
    fi
    cat > "$SYSTEMD_UNIT" <<EOF_SYSTEMD
[Unit]
Description=Kienzlefon Qwen3-TTS 0.6B CUDA service
After=local-fs.target network.target

[Service]
Type=simple
WorkingDirectory=${BASE_DIR}
Environment=LD_LIBRARY_PATH=${CUDA_LIBDIR}
Environment=CUDA_VISIBLE_DEVICES=${KIENZLEFON_SELECTED_GPU_UUID:?}
Environment=QWEN_CUDA_FUSED_TALKER=1
Environment=QWEN_CUDA_CONVDEC=1
${cuda_batch_env}
ExecStart=${BINARY} -d ${MODEL_DIR} --int8 -j ${THREADS} --backend cuda --serve ${PORT} --batch-size ${BATCH_SIZE}
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/server.stdout.log
StandardError=append:${LOG_DIR}/server.stderr.log

[Install]
WantedBy=multi-user.target
EOF_SYSTEMD
    chmod 0644 "$SYSTEMD_UNIT"
    systemctl daemon-reload
  fi
}

port_must_be_free() {
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "TCP port ${PORT} is already in use:"
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
    die "Port ${PORT} must be free after stopping the Qwen3-TTS service."
  fi
}

backend_smoke_tests() {
  log "Smoke-testing selected CUDA INT8 backend (no CPU fallback)..."
  local tmp
  tmp="$(mktemp -d /tmp/kienzlefon-qwen-backend.XXXXXX)"
  CLEANUP_TMP="$tmp"
  CUDA_VISIBLE_DEVICES="${KIENZLEFON_SELECTED_GPU_UUID:?}" \
    LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
    "$BINARY" --gpu-selftest --backend cuda >/dev/null 2>"${tmp}/cuda-selftest.log" || {
      cat "${tmp}/cuda-selftest.log" >&2 || true
      die "CUDA GPU self-test failed; no CPU fallback"
    }
  if ! CUDA_VISIBLE_DEVICES="${KIENZLEFON_SELECTED_GPU_UUID:?}" \
    QWEN_CUDA_FUSED_TALKER=1 QWEN_CUDA_CONVDEC=1 \
    LD_LIBRARY_PATH="${CUDA_LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
    "$BINARY" -d "$MODEL_DIR" --int8 -j "$THREADS" --backend cuda \
      -s uncle_fu -l German --seed "$TEST_SEED" \
      --text "Guten Tag. Dies ist ein kurzer CUDA-Test." -o "${tmp}/cuda.wav" \
      >/dev/null 2>"${tmp}/cuda.log"; then
    cat "${tmp}/cuda.log" >&2 || true
    die "CUDA INT8 smoke test failed; no CPU fallback"
  fi
  validate_wav "${tmp}/cuda.wav" || { cat "${tmp}/cuda.log" >&2; die "CUDA INT8 smoke test produced invalid WAV"; }
  rm -rf "$tmp"
  CLEANUP_TMP=""
}

start_and_healthcheck_service() {
  port_must_be_free
  service_start
  wait_for_health "http://127.0.0.1:${PORT}" 180 || {
    tail -n 120 "${LOG_DIR}/server.stderr.log" >&2 || true
    if [[ "$PLATFORM" == "ubuntu" ]]; then journalctl -u "$SYSTEMD_UNIT_NAME" -n 120 --no-pager >&2 || true; fi
    die "Qwen3-TTS service did not become healthy on port ${PORT}"
  }

  log "Running API healthcheck..."
  "$HEALTH_CMD"

  if [[ "$PLATFORM" == "macos" ]]; then
    log "Verifying launchd unload/reload cycle..."
  else
    log "Verifying systemd stop/start cycle and boot enablement..."
  fi

  service_stop
  port_must_be_free
  service_start
  wait_for_health "http://127.0.0.1:${PORT}" 180 || die "Service failed after service-manager reload"
  "$HEALTH_CMD" >/dev/null

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    systemctl is-enabled --quiet "$SYSTEMD_UNIT_NAME" || die "systemd unit is not enabled for boot"
  fi
  log "Service-manager restart check passed."
}

run_benchmark() {
  local report latest
  report="${LOG_DIR}/benchmark-$(date '+%Y%m%d-%H%M%S').txt"
  latest="${LOG_DIR}/benchmark-latest.txt"

  if [[ "$PLATFORM" == "macos" ]]; then
    log "Running reproducible CPU/Metal INT8/INT8 benchmark..."
  else
    log "Running reproducible CPU/CUDA INT8/INT8 benchmark..."
  fi
  "$BENCH_CMD" | tee "$report"
  cp "$report" "$latest"
  chmod 0644 "$report" "$latest"
}

write_offline_install_metadata() {
  local commit preferred_backend
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  preferred_backend="$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)"
  cat > "${STATE_DIR}/offline-install-info.txt" <<EOF_OFFLINE_INFO
installer_version=${VERSION}
installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
install_mode=offline-one-shot
platform=${PLATFORM}
os_version=${OS_VERSION}
architecture=${ARCH}
repo=${REPO_URL}
git_commit=${commit}
model=${MODEL_HF_ID}
source_dir=${SRC_DIR}
cpu_binary=${CPU_BINARY}
cuda_binary=${CUDA_BINARY}
cuda_available=${CUDA_AVAILABLE}
generator=${GENERATE_CMD}
model_dir=${MODEL_DIR}
threads=${THREADS}
preferred_backend=${preferred_backend}
fallback_backend=cpu
default_quantization=int8
speaker=uncle_fu
language=German
seed=${TEST_SEED}
output_format=wav-pcm-s16le
output_rate=24000
output_channels=1
qwen_service_action=none
pause_units=$(pause_units_csv)
maintenance_marker=${MAINTENANCE_MARKER}
min_available_kib=${MIN_GENERATE_AVAILABLE_KIB}
stop_timeout_seconds=${STOP_TIMEOUT_SECONDS}
readiness_timeout_seconds=${READINESS_TIMEOUT_SECONDS}
installation_generation_test=passed
listener_action=none
cuda_home=${CUDA_HOME}
cuda_libdir=${CUDA_LIBDIR}
cuda_arch=${CUDA_ARCH}
cuda_gpu=${CUDA_GPU_NAME}
EOF_OFFLINE_INFO
  chmod 0644 "${STATE_DIR}/offline-install-info.txt"
}

print_offline_summary() {
  local commit preferred_backend existing_service
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  preferred_backend="$([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo cuda || echo cpu)"
  existing_service="none detected"
  if [[ -e "$PLIST" || -e "$SYSTEMD_UNIT" ]]; then
    existing_service="present and deliberately unchanged"
  fi

  cat <<EOF_OFFLINE_SUMMARY

====================================================================
Kienzlefon Qwen3-TTS 0.6B offline installation complete
====================================================================

Platform          : ${PLATFORM} ${OS_VERSION} / ${ARCH}
Installation path : ${BASE_DIR}
Source path       : ${SRC_DIR}
CPU binary        : ${CPU_BINARY}
CUDA binary       : $([[ "$CUDA_AVAILABLE" -eq 1 ]] && echo "$CUDA_BINARY" || echo "not installed/usable")
Model             : ${MODEL_HF_ID}
Model path        : ${MODEL_DIR}
Git commit        : ${commit}  (pinned by installer 2.0)
Generator         : ${GENERATE_CMD}
Preferred backend : ${preferred_backend}
Fallback backend  : CPU INT8
Default voice     : uncle_fu
Default language  : German
Default seed      : ${TEST_SEED}
Output format     : WAV, PCM S16LE, 24000 Hz, mono
Qwen service      : none
Paused ASR units  : $([[ ${#PAUSE_UNITS[@]} -gt 0 ]] && pause_units_csv || echo "none detected")
RAM preflight     : 5 GiB MemAvailable after ASR stop (Linux)
Stop timeout      : ${STOP_TIMEOUT_SECONDS} seconds
Readiness timeout : ${READINESS_TIMEOUT_SECONDS} seconds
Install E2E test  : passed (ASR stop/generate/restore path)
Port/listener     : none created by offline-only mode
Existing Qwen svc.: ${existing_service}
Resident RAM/VRAM : none after each generator process exits

Example:
  sudo ${GENERATE_CMD} \
    --text "Unsere Praxis ist heute geschlossen." \
    --output /tmp/ansage.wav

Replace an existing WAV atomically:
  sudo ${GENERATE_CMD} \
    --text "Unsere Praxis ist heute geschlossen." \
    --output /tmp/ansage.wav \
    --force

Uninstall  : sudo ${SCRIPT_NAME} --uninstall
Keep model : sudo ${SCRIPT_NAME} --uninstall --keep-model

Note: --offline-only starts no Qwen HTTP server and opens no port. A pre-existing
Qwen service remains unchanged. During each generation, only the listed ASR units
that were active are stopped temporarily and verified before the WAV is activated.
====================================================================
EOF_OFFLINE_SUMMARY
}

write_install_metadata() {
  local commit gpu_backend
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  if [[ "$PLATFORM" == "macos" ]]; then gpu_backend="metal"; else gpu_backend="cuda"; fi
  cat > "${STATE_DIR}/install-info.txt" <<EOF_INFO
installer_version=${VERSION}
installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
platform=${PLATFORM}
os_version=${OS_VERSION}
architecture=${ARCH}
repo=${REPO_URL}
git_commit=${commit}
model=${MODEL_HF_ID}
source_dir=${SRC_DIR}
binary=${BINARY}
model_dir=${MODEL_DIR}
port=${PORT}
threads=${THREADS}
batch_size=${BATCH_SIZE}
default_backend=$([[ "$PLATFORM" == "ubuntu" ]] && echo cuda || echo cpu)
default_quantization=int8
optional_gpu_backend=${gpu_backend}
speaker=uncle_fu
language=German
stream_format=s16le
stream_rate=24000
stream_channels=1
cuda_home=${CUDA_HOME}
cuda_libdir=${CUDA_LIBDIR}
cuda_arch=${CUDA_ARCH}
cuda_gpu=${CUDA_GPU_NAME}
EOF_INFO
  chmod 0644 "${STATE_DIR}/install-info.txt"
}

print_summary() {
  local commit gpu_modes service_desc service_file
  commit="$(git -C "$SRC_DIR" rev-parse HEAD)"
  if [[ "$PLATFORM" == "macos" ]]; then
    gpu_modes="Metal INT8 / Metal INT8"
    service_desc="launchd: ${LABEL}"
    service_file="$PLIST"
  else
    gpu_modes="CUDA INT8 / CUDA INT8"
    service_desc="systemd: ${SYSTEMD_UNIT_NAME}"
    service_file="$SYSTEMD_UNIT"
  fi

  cat <<EOF_SUMMARY

====================================================================
Kienzlefon Qwen3-TTS 0.6B installation complete
====================================================================

Platform          : ${PLATFORM} ${OS_VERSION} / ${ARCH}
Installation path : ${BASE_DIR}
Source path       : ${SRC_DIR}
Binary            : ${BINARY}
Model             : ${MODEL_HF_ID}
Model path        : ${MODEL_DIR}
Git commit        : ${commit}  (pinned by installer 2.0)
Server port       : ${PORT} (upstream binds all IPv4 interfaces)
Local server URL  : http://127.0.0.1:${PORT}
Service           : ${service_desc}
Service file      : ${service_file}
Default mode      : ${STANDARD_MODE}, ${THREADS} threads, batch size ${BATCH_SIZE}
Available modes   : CPU INT8 / CPU INT8 / ${gpu_modes}
Default API voice : uncle_fu
Kienzlefon lang.  : German (send explicitly per request)
Streaming format  : raw PCM s16le, 24000 Hz, mono
EOF_SUMMARY

  if [[ "$PLATFORM" == "ubuntu" ]]; then
    cat <<EOF_CUDA
CUDA GPU          : ${CUDA_GPU_NAME}
CUDA Toolkit      : ${CUDA_HOME}
CUDA build arch   : ${CUDA_ARCH}
Note              : CUDA is the default service backend; CPU remains available for benchmark/fallback.
EOF_CUDA
  else
    echo "Note              : Metal is available but NOT used by the default service."
  fi

  cat <<EOF_REQUESTS

Primary streaming request:
  curl -sN http://127.0.0.1:${PORT}/v1/tts/stream \\
    -H 'Content-Type: application/json' \\
    -d '{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"uncle_fu","language":"German"}' \\
    -o output.pcm

Full WAV request:
  curl -s http://127.0.0.1:${PORT}/v1/tts \\
    -H 'Content-Type: application/json' \\
    -d '{"text":"Guten Tag. Wie kann ich Ihnen helfen?","speaker":"uncle_fu","language":"German"}' \\
    -o output.wav

OpenAI-compatible WAV request:
  curl -s http://127.0.0.1:${PORT}/v1/audio/speech \\
    -H 'Content-Type: application/json' \\
    -d '{"input":"Guten Tag. Wie kann ich Ihnen helfen?","voice":"uncle_fu","language":"German"}' \\
    -o output-openai.wav

Healthcheck : ${HEALTH_CMD}
Benchmark   : sudo ${BENCH_CMD}
Status      : ${CTL_CMD} status
Start       : sudo ${CTL_CMD} start
Stop        : sudo ${CTL_CMD} stop
Restart     : sudo ${CTL_CMD} restart
Logs        : ${CTL_CMD} logs
Uninstall   : sudo ${SCRIPT_NAME} --uninstall
Keep model  : sudo ${SCRIPT_NAME} --uninstall --keep-model

Benchmark report:
  ${LOG_DIR}/benchmark-latest.txt
====================================================================
EOF_REQUESTS

  if [[ -f "${LOG_DIR}/benchmark-latest.txt" ]]; then
    echo
    echo "Latest benchmark:"
    cat "${LOG_DIR}/benchmark-latest.txt"
  fi
}

main() {
  if (( UNINSTALL == 1 )); then
    uninstall_all
    return 0
  fi

  log "Starting Kienzlefon Qwen3-TTS cross-platform installer v${VERSION}"
  check_platform_and_tools
  prepare_directories
  install_source

  if (( OFFLINE_ONLY == 1 )); then
    log "Offline-only mode selected: no service definition, autostart, HTTP server, or listener will be created."
    detect_pause_units
    build_offline_cpu_binary
    build_offline_cuda_binary
    download_model
    write_offline_env_file
    install_generate_command
    offline_smoke_tests
    write_offline_install_metadata
    print_offline_summary
    return 0
  fi

  build_binary
  download_model
  write_env_file
  install_ttfa_helper
  install_control_command
  install_health_command
  install_benchmark_command
  write_service_definition
  backend_smoke_tests
  start_and_healthcheck_service

  if (( RUN_BENCHMARK == 1 )); then
    run_benchmark
    wait_for_health "http://127.0.0.1:${PORT}" 180 || die "Service was not healthy after benchmark restoration"
  else
    warn "Benchmark skipped by request. Run later with: sudo ${BENCH_CMD}"
  fi

  write_install_metadata
  print_summary
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
__KZF_QWEN_V2_PAYLOAD__
}

write_diarization_server() {
  cat <<'__KZF_PYANNOTE_V2_PAYLOAD__'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optionaler lokaler pyannote Community-1-Dienst für Kienzlefon AI 2.0."""

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import torch
import torchaudio
from pyannote.audio import Pipeline

HOST = os.environ.get('DIARIZATION_HOST', '0.0.0.0')
PORT = int(os.environ.get('DIARIZATION_PORT', '8183'))
MODEL = os.environ.get('PYANNOTE_MODEL', 'pyannote/speaker-diarization-community-1')
DEVICE = os.environ.get('DIARIZATION_DEVICE', 'cuda:0').strip().lower()
TOKEN = os.environ.get('HF_TOKEN') or os.environ.get('HUGGINGFACE_TOKEN')
MAX_BYTES = int(os.environ.get('DIARIZATION_MAX_BYTES', str(100 * 1024 * 1024)))

print('Lade Diarisierungsmodell:', MODEL, flush=True)
kwargs = {}
if TOKEN:
    kwargs['token'] = TOKEN
if not DEVICE.startswith('cuda'):
    raise RuntimeError(
        'Dieser WhisperDoku-Dienst ist absichtlich GPU-only. '
        'DIARIZATION_DEVICE muss cuda oder cuda:N sein.'
    )

if not torch.cuda.is_available():
    raise RuntimeError(
        'CUDA ist für PyTorch nicht verfügbar. Kein CPU-Fallback erlaubt.'
    )

device = torch.device(DEVICE)
gpu_index = 0 if device.index is None else device.index
if gpu_index >= torch.cuda.device_count():
    raise RuntimeError(
        'Angeforderte GPU %d existiert nicht; verfügbar: %d'
        % (gpu_index, torch.cuda.device_count())
    )

gpu_name = torch.cuda.get_device_name(gpu_index)
torch.set_float32_matmul_precision('high')

pipeline = Pipeline.from_pretrained(MODEL, **kwargs)
pipeline.to(device)

print(
    'Diarisierungsmodell bereit | device=%s | gpu=%s | torch_cuda=%s | port=%d'
    % (DEVICE, gpu_name, torch.version.cuda, PORT),
    flush=True,
)

pipeline_lock = threading.Lock()


def annotation_segments(annotation):
    out = []
    if annotation is None:
        return out
    try:
        for turn, speaker in annotation:
            out.append({
                'start': float(turn.start),
                'end': float(turn.end),
                'speaker': str(speaker),
            })
        return out
    except Exception:
        pass
    try:
        for turn, track, speaker in annotation.itertracks(yield_label=True):
            out.append({
                'start': float(turn.start),
                'end': float(turn.end),
                'speaker': str(speaker),
            })
    except Exception as exc:
        raise RuntimeError('Unbekanntes pyannote-Ausgabeformat: %s' % exc)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = 'KienzlefonDiarization/2.0'

    def log_message(self, fmt, *args):
        # Nur technische HTTP-Metadaten; niemals Audio/Transkriptinhalt loggen.
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlsplit(self.path).path == '/health':
            self.send_json(200, {
                'ok': True,
                'model': MODEL,
                'device': DEVICE,
                'gpu': gpu_name,
                'torch_cuda': torch.version.cuda,
                'cuda_available': torch.cuda.is_available(),
                'vram_allocated_mb': round(torch.cuda.memory_allocated(gpu_index) / 1024 / 1024, 1),
                'vram_reserved_mb': round(torch.cuda.memory_reserved(gpu_index) / 1024 / 1024, 1),
            })
        else:
            self.send_json(404, {'error': 'not_found'})

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/v1/diarize':
            self.send_json(404, {'error': 'not_found'})
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BYTES:
            self.send_json(413, {'error': 'invalid_content_length'})
            return

        body = self.rfile.read(length)
        query = parse_qs(parsed.query)

        def one_int(name):
            values = query.get(name)
            if not values:
                return None
            return int(values[0])

        num_speakers = one_int('num_speakers')
        min_speakers = one_int('min_speakers')
        max_speakers = one_int('max_speakers')

        call_kwargs = {}
        if num_speakers is not None:
            call_kwargs['num_speakers'] = num_speakers
        else:
            if min_speakers is not None:
                call_kwargs['min_speakers'] = min_speakers
            if max_speakers is not None:
                call_kwargs['max_speakers'] = max_speakers

        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(body)
                tmp_name = tmp.name

            # Audio einmal in den Speicher laden. Pyannote empfiehlt diese
            # Form für schnellere Verarbeitung und vermeidet wiederholtes
            # Dateidecoding innerhalb der Pipeline.
            waveform, sample_rate = torchaudio.load(tmp_name)
            audio_input = {
                'waveform': waveform,
                'sample_rate': sample_rate,
            }

            with pipeline_lock, torch.inference_mode():
                output = pipeline(audio_input, **call_kwargs)

            exclusive = getattr(output, 'exclusive_speaker_diarization', None)
            if exclusive is not None:
                annotation = exclusive
                mode = 'exclusive'
            else:
                annotation = getattr(output, 'speaker_diarization', None)
                mode = 'regular'

            segments = annotation_segments(annotation)
            speakers = sorted({x['speaker'] for x in segments})
            self.send_json(200, {
                'ok': True,
                'model': MODEL,
                'device': DEVICE,
                'mode': mode,
                'speakers': speakers,
                'segments': segments,
            })
        except Exception as exc:
            print('Diarisierungsfehler: %r' % (exc,), flush=True)
            self.send_json(500, {'error': 'diarization_failed', 'detail': str(exc)})
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


if __name__ == '__main__':
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print('WhisperDoku Diarisierung auf %s:%d' % (HOST, PORT), flush=True)
    httpd.serve_forever()
__KZF_PYANNOTE_V2_PAYLOAD__
}

main "$@"
