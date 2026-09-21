#!/usr/bin/env bash
set -euo pipefail

VERSION="1.20.1"
ARCHIVE="mediamtx_v${VERSION}_linux_arm64.tar.gz"
BASE_URL="https://github.com/bluenviron/mediamtx/releases/download/v${VERSION}"
INSTALL_DIR="${HOME}/.local/bin"
TEMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

mkdir -p "$INSTALL_DIR"
curl --fail --location --silent --show-error "$BASE_URL/$ARCHIVE" -o "$TEMP_DIR/$ARCHIVE"
curl --fail --location --silent --show-error "$BASE_URL/checksums.sha256" -o "$TEMP_DIR/checksums.sha256"

EXPECTED_LINE="$(grep "[ *]${ARCHIVE}$" "$TEMP_DIR/checksums.sha256" || true)"
if [[ -z "$EXPECTED_LINE" ]]; then
  echo "No se encontro el checksum de $ARCHIVE" >&2
  exit 1
fi

printf '%s\n' "$EXPECTED_LINE" > "$TEMP_DIR/archive.sha256"
(
  cd "$TEMP_DIR"
  sha256sum --check archive.sha256
)

tar -xzf "$TEMP_DIR/$ARCHIVE" -C "$TEMP_DIR" mediamtx LICENSE
install -m 755 "$TEMP_DIR/mediamtx" "$INSTALL_DIR/mediamtx"
install -m 644 "$TEMP_DIR/LICENSE" "$INSTALL_DIR/mediamtx-LICENSE"

"$INSTALL_DIR/mediamtx" --version
