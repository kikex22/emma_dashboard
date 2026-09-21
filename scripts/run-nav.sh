#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros-env.sh"

LIDAR_PORT="${EMMA_LIDAR_PORT:-/dev/lidar}"

if [[ ! -e "$LIDAR_PORT" ]]; then
  echo "ERROR: LIDAR no existe en $LIDAR_PORT"
  exit 1
fi

# Mirror C9 without tmux: one systemd cgroup owns LIDAR, Isabel and Nav2.
ros2 launch sllidar_ros2 sllidar_a1_launch.py \
  serial_port:="$LIDAR_PORT" \
  serial_baudrate:=115200 \
  frame_id:=lidar_frame \
  scan_mode:=Sensitivity &

ros2 launch isabel emma.launch.py &

# Give Isabel time to publish the arm/robot state before Nav2 starts.
sleep 2

exec ros2 launch carolina nav.launch.py \
  use_rviz:="${EMMA_NAV_USE_RVIZ:-false}" \
  enable_lidar:=false
