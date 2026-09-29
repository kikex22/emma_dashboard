#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
GUARD_SOURCE="$SCRIPT_DIR/emma-clock-guard"
GUARD_TARGET="/usr/local/libexec/emma-clock-guard"
SYSTEMD_SOURCE="$PROJECT_DIR/systemd"
MIN_VALID_EPOCH=1600000000
TIMEZONE="${EMMA_TIMEZONE:-America/Caracas}"

for source in \
  "$GUARD_SOURCE" \
  "$SYSTEMD_SOURCE/emma-clock-restore.service" \
  "$SYSTEMD_SOURCE/emma-clock-save.service" \
  "$SYSTEMD_SOURCE/emma-clock-save.timer"; do
  if [[ ! -f "$source" ]]; then
    echo "ERROR: no existe $source"
    exit 1
  fi
done

if (( EUID != 0 )); then
  exec sudo "$0" "$@"
fi

if (( $(date +%s) <= MIN_VALID_EPOCH )); then
  echo "ERROR: sincroniza el Orin por WiFi antes de instalar esta correccion."
  exit 1
fi

install -d -m 0755 /usr/local/libexec
install -m 0755 "$GUARD_SOURCE" "$GUARD_TARGET"
install -m 0644 "$SYSTEMD_SOURCE/emma-clock-restore.service" /etc/systemd/system/
install -m 0644 "$SYSTEMD_SOURCE/emma-clock-save.service" /etc/systemd/system/
install -m 0644 "$SYSTEMD_SOURCE/emma-clock-save.timer" /etc/systemd/system/

timedatectl set-timezone "$TIMEZONE"
"$GUARD_TARGET" save
systemctl daemon-reload
systemctl enable --now emma-clock-restore.service emma-clock-save.timer

echo "Correccion de reloj instalada."
systemctl status emma-clock-restore.service emma-clock-save.timer --no-pager
timedatectl status
