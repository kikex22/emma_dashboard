#!/usr/bin/env bash
set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/emma-arm-cam-reset"
USER_NAME="${SUDO_USER:-$USER}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Ejecuta: sudo $0"
  exit 1
fi

cat > "$SUDOERS_FILE" <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/sbin/uhubctl -l 1-2 -p 1 -a cycle -d 2, /usr/bin/udevadm control --reload-rules, /usr/bin/udevadm trigger --action=add --subsystem-match=video4linux, /usr/bin/udevadm settle
EOF

chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE"
echo "Arm cam sudoers instalado en $SUDOERS_FILE para usuario $USER_NAME"
