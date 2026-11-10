#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPPORT_DIR="$HOME/Library/Application Support/Kienzledoku"
PRESEED=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --config) PRESEED="${2:?TOML-Datei fehlt}"; shift ;;
    --help) echo 'install_macos.command [--config /pfad/config.toml]'; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done
BASE_PYTHON="${KIENZLEDOKU_PYTHON:-$(command -v python3 || true)}"
[ -n "$BASE_PYTHON" ] || { echo 'Python >=3.9 fehlt.' >&2; exit 1; }
"$BASE_PYTHON" -c 'import sys; assert sys.version_info >= (3,9), "Python >=3.9 erforderlich"'
mkdir -p "$SUPPORT_DIR" "$HOME/Applications"
chmod 700 "$SUPPORT_DIR"
if [ ! -x "$SUPPORT_DIR/venv/bin/python3" ]; then "$BASE_PYTHON" -m venv "$SUPPORT_DIR/venv"; fi
PYTHON3="$SUPPORT_DIR/venv/bin/python3"
"$PYTHON3" -m pip install -r "$SCRIPT_DIR/requirements-asr-client.txt"
if [ ! -x "$SCRIPT_DIR/kienzledoku_window" ]; then "$SCRIPT_DIR/build_native_window_macos.sh"; fi
if [ ! -x "$SCRIPT_DIR/kienzleconnect" ]; then "$SCRIPT_DIR/build_connect.sh"; fi
cp "$SCRIPT_DIR"/kienzledoku*.py "$SUPPORT_DIR/"
cp "$SCRIPT_DIR/prompt_documentation.txt" "$SCRIPT_DIR/requirements-asr-client.txt" "$SCRIPT_DIR/start_kienzledoku_asr.sh" "$SCRIPT_DIR/kienzledoku_window" "$SCRIPT_DIR/kienzleconnect" "$SUPPORT_DIR/"
mkdir -p "$SUPPORT_DIR/assets"
cp "$SCRIPT_DIR"/assets/* "$SUPPORT_DIR/assets/"
if [ ! -f "$SUPPORT_DIR/config.toml" ]; then
  if [ -n "$PRESEED" ]; then
    "$PYTHON3" "$SUPPORT_DIR/kienzledoku.py" --import-config "$PRESEED"
  else
    (cd "$SUPPORT_DIR" && "$PYTHON3" -c 'import kienzledoku_config as c; c.initialize_installation()')
  fi
fi
# Keep bundle identifiers/legacy data paths stable across upgrades.
escape_as() { printf '%s' "$1" | sed 's/\\/\\\\/g;s/"/\\"/g'; }
PY_AS="$(escape_as "$PYTHON3")"
SCRIPT_AS="$(escape_as "$SUPPORT_DIR/kienzledoku.py")"
CONNECT_AS="$(escape_as "$SUPPORT_DIR/kienzleconnect")"
for mode in record connect; do
  if [ "$mode" = record ]; then
    APP_DIR="$HOME/Applications/kienzledoku record.app"
    BUNDLE_ID='de.kienzledoku.app'
    SCHEME='kienzledoku-record'
  else
    APP_DIR="$HOME/Applications/kienzledoku connect.app"
    BUNDLE_ID='de.kienzledoku.connect'
    SCHEME='kienzledoku'
  fi
  TEMP_AS="$(mktemp -t kienzledoku-install)"
  cat > "$TEMP_AS" <<APPLESCRIPT
property pythonPath : "$PY_AS"
property scriptPath : "$SCRIPT_AS"
property connectPath : "$CONNECT_AS"
property appMode : "$mode"
on run
    do shell script (quoted form of pythonPath) & " " & (quoted form of scriptPath) & " --settings >/dev/null 2>&1 &"
end run
on open location theURL
    if appMode is "connect" then
        set commandText to "KIENZLEDOKU_PYTHON=" & (quoted form of pythonPath) & " " & (quoted form of connectPath) & " --deep-link-stdin"
    else
        set commandText to (quoted form of pythonPath) & " " & (quoted form of scriptPath) & " --deep-link-stdin"
    end if
    do shell script "printf '%s' " & (quoted form of theURL) & " | " & commandText & " >/dev/null 2>&1 &"
end open location
APPLESCRIPT
  # Build into a temporary bundle; preserve previous installation until ready.
  TEMP_APP_DIR="$(mktemp -d -t kienzledoku-app)"
  /usr/bin/osacompile -o "$TEMP_APP_DIR/app.app" "$TEMP_AS"
  rm -f "$TEMP_AS"
  PLIST="$TEMP_APP_DIR/app.app/Contents/Info.plist"
  "$PYTHON3" - "$PLIST" "$BUNDLE_ID" "$SCHEME" "$mode" <<'PY'
import plistlib,sys
path,ident,scheme,mode=sys.argv[1:]
with open(path,'rb') as f: p=plistlib.load(f)
p.update(CFBundleIdentifier=ident,CFBundleName='kienzledoku '+mode,CFBundleDisplayName='kienzledoku '+mode,
         CFBundleShortVersionString='1.3.3',CFBundleVersion='1.3.3',LSUIElement=True,
         NSMicrophoneUsageDescription='kienzledoku record benötigt das Mikrofon für die Gesprächsaufzeichnung.',
         CFBundleIconFile='applet.icns',
         CFBundleURLTypes=[dict(CFBundleURLName=ident,CFBundleURLSchemes=[scheme])])
with open(path,'wb') as f: plistlib.dump(p,f)
PY
  cp "$SUPPORT_DIR/assets/kienzledoku-record.icns" "$TEMP_APP_DIR/app.app/Contents/Resources/applet.icns"
  /usr/bin/codesign --force --deep --sign - "$TEMP_APP_DIR/app.app"
  /usr/bin/codesign --verify --deep --strict "$TEMP_APP_DIR/app.app"
  if [ -d "$APP_DIR" ]; then mv "$APP_DIR" "$TEMP_APP_DIR/previous.app"; fi
  mv "$TEMP_APP_DIR/app.app" "$APP_DIR"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DIR"
done
OLD_APP="$HOME/Applications/Kienzledoku.app"
if [ -f "$OLD_APP/Contents/Info.plist" ] && [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$OLD_APP/Contents/Info.plist" 2>/dev/null || true)" = 'de.kienzledoku.app' ]; then
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$OLD_APP" || true
  mv "$OLD_APP" "$TEMP_APP_DIR/legacy-record.app"
fi
"$PYTHON3" "$SUPPORT_DIR/kienzledoku.py" --self-test
"$PYTHON3" "$SUPPORT_DIR/kienzledoku.py" --settings >/dev/null 2>&1 &
echo 'kienzledoku record 1.3.3 installiert. Bestehende Einstellungen bleiben erhalten.'
echo 'Direkt: kienzledoku-record://record · Connect: kienzledoku://record'
