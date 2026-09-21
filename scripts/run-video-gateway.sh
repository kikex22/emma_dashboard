#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MEDIAMTX_BIN="${HOME}/.local/bin/mediamtx"

if [[ ! -x "$MEDIAMTX_BIN" ]]; then
  echo "MediaMTX no esta instalado. Ejecuta scripts/install-mediamtx.sh" >&2
  exit 17
fi

exec "$MEDIAMTX_BIN" "$PROJECT_DIR/config/mediamtx.yml"
