#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

python3 -m venv --system-site-packages "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"
npm install --prefix "$PROJECT_DIR"

echo "Dashboard listo. Inicia con: $PROJECT_DIR/run.sh"

