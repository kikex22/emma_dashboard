#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros-env.sh"

export EMMA_ARM_NO_ATTACH=1
export TERM="${TERM:-xterm-256color}"

exec /usr/bin/script -qefc /home/jetson/emma/scripts/arm_only.sh /dev/null
