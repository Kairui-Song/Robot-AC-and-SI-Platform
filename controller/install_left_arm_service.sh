#!/bin/bash
set -euo pipefail

SOURCE="${1:-ethercat_left_arm_test.py}"
BENCHMARK_SOURCE="${2:-control_benchmark.py}"
DANCE_SOURCE="${3:-dance_flow.sh}"
INSTALL_DIR="/opt/linglong"
TARGET="$INSTALL_DIR/ethercat_left_arm_test.py"
BENCHMARK_TARGET="$INSTALL_DIR/control_benchmark.py"
DANCE_TARGET="$INSTALL_DIR/dance_flow.sh"
SUDOERS="/etc/sudoers.d/linglong-ethercat"

if ! command -v ethercat >/dev/null 2>&1; then
    echo "ERROR: ethercat command not found" >&2
    exit 1
fi

sudo install -d -o root -g root -m 0755 "$INSTALL_DIR"
sudo install -o root -g root -m 0755 "$SOURCE" "$TARGET"
sudo install -o root -g root -m 0755 "$BENCHMARK_SOURCE" "$BENCHMARK_TARGET"
sudo install -o root -g root -m 0755 "$DANCE_SOURCE" "$DANCE_TARGET"
sudo ethercat -m 0 slaves

echo "Installed: $TARGET"
echo "Installed: $BENCHMARK_TARGET"
echo "Installed: $DANCE_TARGET"
echo "If passwordless operation is preferred, validate and install this sudoers rule:"
echo "enpht ALL=(root) NOPASSWD: /usr/bin/python3 $TARGET *"
echo "Use visudo -cf before copying a rule into $SUDOERS."
