#!/usr/bin/env bash
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros-env.sh"

if ros2 node list 2>/dev/null | grep -qx '/isa_node'; then
  echo "ISA ya esta activo fuera de emma-isa.service" >&2
  exit 16
fi

# 1. Arrancar el entorno que ISA necesita
ros2 launch isabel emma_system2.launch.py &
ENV_PID=$!

# Dar tiempo al entorno para iniciar
sleep 3

# 2. Arrancar ISA
ISA_EXEC="$(ros2 pkg prefix isabel)/lib/isabel/isa"
"$ISA_EXEC" &
ISA_PID=$!

stop_pid() {
  local pid="$1"
  local signal="$2"
  local attempts="$3"

  kill "-$signal" "$pid" 2>/dev/null || true
  for _ in $(seq 1 "$attempts"); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cleanup() {
  stop_pid "$ISA_PID" SIGINT 5 || stop_pid "$ISA_PID" SIGTERM 3 || kill -KILL "$ISA_PID" 2>/dev/null || true
  stop_pid "$ENV_PID" SIGINT 10 || stop_pid "$ENV_PID" SIGTERM 5 || kill -KILL "$ENV_PID" 2>/dev/null || true
  wait "$ISA_PID" "$ENV_PID" 2>/dev/null || true
}

trap 'cleanup; exit 0' INT TERM

# Mantener el servicio vivo mientras ambos procesos existen
wait -n "$ENV_PID" "$ISA_PID"
EXIT_STATUS=$?

# Si uno termina, detener el otro también
cleanup
exit "$EXIT_STATUS"
