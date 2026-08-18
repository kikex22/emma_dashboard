#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ROS 2 del Orin
source /opt/ros/humble/setup.bash

# Workspace EMMA del Orin
if [[ -f /home/jetson/emma/install/setup.bash ]]; then
  source /home/jetson/emma/install/setup.bash
fi

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-99}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file:///home/jetson/.ros/cyclonedds.xml}"

unset ROS_LOCALHOST_ONLY

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Falta el entorno virtual."
  echo "Ejecuta: python3 -m venv --system-site-packages $PROJECT_DIR/.venv"
  exit 1
fi

exec "$PROJECT_DIR/.venv/bin/python" -m uvicorn \
  emma_dashboard.server:app \
  --app-dir "$PROJECT_DIR" \
  --host "${EMMA_DASHBOARD_HOST:-0.0.0.0}" \
  --port "${EMMA_DASHBOARD_PORT:-8765}"
