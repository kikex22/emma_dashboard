#!/usr/bin/env bash
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros-env.sh"

if ros2 node list 2>/dev/null | grep -qx '/isa_node'; then
  echo "ISA ya esta activo fuera de emma-isa.service" >&2
  exit 16
fi

# C27 (controller, odom, base mux y EMMA ARM) vive en emma-manual.service.
# ISA se monta encima de ese entorno y no debe lanzar una segunda instancia.
ISA_EXEC="$(ros2 pkg prefix isabel)/lib/isabel/isa"
exec "$ISA_EXEC"
