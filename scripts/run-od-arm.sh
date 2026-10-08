#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_DIR/scripts/ros-env.sh"
exec ros2 run od arm_cam_udp udp://5602 --dashboard
