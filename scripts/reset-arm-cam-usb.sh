#!/usr/bin/env bash
set -euo pipefail

HUB_LOCATION="${EMMA_ARM_CAM_USB_HUB:-1-2}"
HUB_PORT="${EMMA_ARM_CAM_USB_PORT:-1}"
CYCLE_DELAY="${EMMA_ARM_CAM_USB_DELAY:-2}"
DEVICE="${EMMA_ARM_CAM_DEVICE:-/dev/v4l/by-id/usb-icSpring_icspring_camera-video-index0}"

say() {
  printf '[ARM_CAM_RESET] %s\n' "$*" >&2
}

wait_for_device() {
  local limit="${1:-20}"
  local i

  for i in $(seq 1 "$limit"); do
    if [[ -e "$DEVICE" ]]; then
      say "lista: $DEVICE"
      return 0
    fi
    sleep 0.5
  done

  say "no aparecio: $DEVICE"
  return 1
}

say "ciclando USB hub=${HUB_LOCATION} port=${HUB_PORT} delay=${CYCLE_DELAY}s"
sudo /usr/sbin/uhubctl -l "$HUB_LOCATION" -p "$HUB_PORT" -a cycle -d "$CYCLE_DELAY"

sudo /usr/bin/udevadm control --reload-rules >/dev/null 2>&1 || true
sudo /usr/bin/udevadm trigger --action=add --subsystem-match=video4linux >/dev/null 2>&1 || true
sudo /usr/bin/udevadm settle >/dev/null 2>&1 || true

wait_for_device 20
