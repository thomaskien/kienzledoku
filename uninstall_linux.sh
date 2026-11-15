#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$SCRIPT_DIR/installer/linux_cli.py" --uninstall "$@"
