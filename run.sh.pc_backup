#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source /opt/ros/jazzy/setup.bash
if [[ -f /home/adjor/Emma/install/setup.bash ]]; then
  source /home/adjor/Emma/install/setup.bash
fi

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-99}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file:///home/adjor/.ros/cyclonedds.xml}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
unset ROS_LOCALHOST_ONLY

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Falta el entorno virtual. Ejecuta: $PROJECT_DIR/setup.sh"
  exit 1
fi

exec "$PROJECT_DIR/.venv/bin/python" -m uvicorn \
  emma_dashboard.server:app \
  --app-dir "$PROJECT_DIR" \
  --host "${EMMA_DASHBOARD_HOST:-127.0.0.1}" \
  --port "${EMMA_DASHBOARD_PORT:-8765}"
