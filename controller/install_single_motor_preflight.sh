#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:-single_motor_preflight.c}"
INSTALL_DIR="/opt/linglong/bin"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT

if ! command -v gcc >/dev/null 2>&1; then
    echo "ERROR: gcc not found" >&2
    exit 1
fi
if ! printf '#include <ecrt.h>\n' | gcc -E -x c - >/dev/null 2>&1; then
    echo "ERROR: ecrt.h not found; install the matching IgH development files" >&2
    exit 1
fi

gcc -O2 -Wall -Wextra -Werror "$SOURCE" -o "$BUILD_DIR/controller_test_client" -lethercat
sudo install -d -o root -g root -m 0755 "$INSTALL_DIR"
sudo install -o root -g root -m 0755 "$BUILD_DIR/controller_test_client" "$INSTALL_DIR/controller_test_client"
sudo "$INSTALL_DIR/controller_test_client" --master 0
