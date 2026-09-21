#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="/dev/v4l/by-id/usb-icSpring_icspring_camera-video-index0"
RESET_SCRIPT="$PROJECT_DIR/scripts/reset-arm-cam-usb.sh"

source "$PROJECT_DIR/scripts/ros-env.sh"

wait_for_device() {
  local limit="${1:-16}"
  local i

  for i in $(seq 1 "$limit"); do
    if [[ -e "$DEVICE" ]]; then
      return 0
    fi
    sleep 0.5
  done

  return 1
}

if ! wait_for_device 2; then
  echo "Arm cam no aparece; intentando reset USB..." >&2
  if ! "$RESET_SCRIPT"; then
    echo "Arm cam reset fallo. Instala sudoers con scripts/install-arm-cam-reset-sudoers.sh" >&2
    exit 16
  fi
fi

if ! wait_for_device 20; then
  echo "Arm cam no volvio despues del reset: $DEVICE" >&2
  exit 1
fi

if fuser "$DEVICE" >/dev/null 2>&1; then
  echo "Arm cam ocupada por otro proceso: $DEVICE" >&2
  exit 16
fi

exec ros2 run od arm_cam_udp "$DEVICE" --dashboard
