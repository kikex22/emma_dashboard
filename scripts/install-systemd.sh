#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="/home/jetson/.config/systemd/user"

install -d -m 755 "$UNIT_DIR"
chmod 755 \
  "$PROJECT_DIR/scripts/ros-env.sh" \
  "$PROJECT_DIR/scripts/run-nav.sh" \
  "$PROJECT_DIR/scripts/run-patrol.sh" \
  "$PROJECT_DIR/scripts/run-video-gateway.sh" \
  "$PROJECT_DIR/scripts/run-astra-depth.sh" \
  "$PROJECT_DIR/scripts/run-od-astra.sh" \
  "$PROJECT_DIR/scripts/run-od-arm.sh" \
  "$PROJECT_DIR/scripts/run-arm.sh" \
  "$PROJECT_DIR/scripts/reset-arm-cam-usb.sh" \
  "$PROJECT_DIR/scripts/install-arm-cam-reset-sudoers.sh" \
  "$PROJECT_DIR/scripts/run-isa.sh"
install -m 644 "$PROJECT_DIR/systemd/emma-dashboard.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-nav.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-patrol.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-video.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-astra-depth.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-od-astra.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-od-arm.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-vision.target" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-isa.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-evaluation.service" "$UNIT_DIR/"
install -m 644 "$PROJECT_DIR/systemd/emma-arm.service" "$UNIT_DIR/"

systemctl --user daemon-reload

echo "Servicios instalados sin habilitar arranque automatico."
echo "Dashboard: systemctl --user start emma-dashboard"
echo "Vision: systemctl --user start emma-vision.target"
echo "ISA local: systemctl --user start emma-isa.service"
echo "Brazo: systemctl --user start emma-arm.service"
echo "Evaluation: se inicia bajo demanda desde el dashboard"
