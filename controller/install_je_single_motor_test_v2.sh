#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:-je_single_motor_test_v2.cpp}"
INSTALL_DIR="/opt/linglong/bin"
TARGET="$INSTALL_DIR/je_single_motor_test_v2"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT

if ! command -v g++ >/dev/null 2>&1; then
    echo "ERROR: g++ not found" >&2
    exit 1
fi
if ! printf '#include <ecrt.h>\n' | g++ -E -x c++ - >/dev/null 2>&1; then
    echo "ERROR: ecrt.h not found; install matching IgH development files" >&2
    exit 1
fi
if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: source not found: $SOURCE" >&2
    exit 1
fi

g++ -O2 -Wall -Wextra -Werror "$SOURCE" -o "$BUILD_DIR/je_single_motor_test_v2" -lethercat
sudo install -d -o root -g root -m 0755 "$INSTALL_DIR"
sudo install -o root -g root -m 0755 "$BUILD_DIR/je_single_motor_test_v2" "$TARGET"
echo "Installed: $TARGET"
sha256sum "$TARGET"
echo "Configure sudoers for this exact executable before starting it from the web UI."
