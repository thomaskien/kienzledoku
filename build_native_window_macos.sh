#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/native/KienzledokuWindow.m"
OUTPUT="$SCRIPT_DIR/kienzledoku_window"
BUILD_DIR="$(mktemp -d /tmp/kienzledoku-window-build.XXXXXX)"
X86_BINARY="$BUILD_DIR/kienzledoku_window-x86_64"
ARM_BINARY="$BUILD_DIR/kienzledoku_window-arm64"

cleanup() {
  rm -f "$X86_BINARY" "$ARM_BINARY"
  rmdir "$BUILD_DIR" 2>/dev/null || true
}
trap cleanup EXIT

CLANG="$(xcrun --find clang)"
SDK="$(xcrun --sdk macosx --show-sdk-path)"

"$CLANG" \
  -isysroot "$SDK" \
  -arch x86_64 \
  -mmacosx-version-min=10.14 \
  -fobjc-arc \
  -framework Cocoa \
  -framework WebKit \
  "$SOURCE" \
  -o "$X86_BINARY"

"$CLANG" \
  -isysroot "$SDK" \
  -arch arm64 \
  -mmacosx-version-min=11.0 \
  -fobjc-arc \
  -framework Cocoa \
  -framework WebKit \
  "$SOURCE" \
  -o "$ARM_BINARY"

lipo -create "$X86_BINARY" "$ARM_BINARY" -output "$OUTPUT"
chmod 700 "$OUTPUT"
codesign --force --sign - "$OUTPUT"
lipo -info "$OUTPUT"
codesign --verify --strict "$OUTPUT"
