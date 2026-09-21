#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"

source "$PROJECT_DIR/scripts/ros-env.sh"

if [[ ! -e "$DEVICE" ]]; then
  echo "Camara Astra RGB no conectada: $DEVICE" >&2
  exit 16
fi

if fuser "$DEVICE" >/dev/null 2>&1; then
  echo "Camara Astra RGB ocupada por otro proceso: $DEVICE" >&2
  exit 16
fi

exec ros2 run od od_node "$DEVICE" --dashboard
