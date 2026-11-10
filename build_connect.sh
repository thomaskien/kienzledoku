#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
cd "$root/connect"
export CGO_ENABLED=0
output="${1:-$root/kienzleconnect}"
if [ "$(uname -s)" = Darwin ] && [ -z "${GOOS:-}" ] && [ -z "${GOARCH:-}" ]; then
  build_dir="$(mktemp -d -t kienzleconnect-build)"
  GOOS=darwin GOARCH=amd64 go build -trimpath -o "$build_dir/amd64" .
  GOOS=darwin GOARCH=arm64 go build -trimpath -o "$build_dir/arm64" .
  lipo -create "$build_dir/amd64" "$build_dir/arm64" -output "$output"
  codesign --force --sign - "$output"
elif [ "${GOOS:-}" = windows ]; then
  go build -trimpath -ldflags=-H=windowsgui -o "$output" .
else
  go build -trimpath -o "$output" .
fi
