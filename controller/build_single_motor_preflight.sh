#!/usr/bin/env bash
set -euo pipefail

SOURCE="${1:-single_motor_preflight.c}"
OUTPUT="${2:-single_motor_preflight}"

if ! command -v gcc >/dev/null 2>&1; then
    echo "ERROR: gcc not found" >&2
    exit 1
fi

gcc -O2 -Wall -Wextra -Werror "$SOURCE" -o "$OUTPUT" -lethercat
echo "Built read-only preflight: $OUTPUT"
