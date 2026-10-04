#!/usr/bin/env bash
set -euo pipefail
stage=/mnt/c/Users/Administrator/Desktop/linglong_1025_2/.ros-system
pkg="$stage/project/ros2_ws/src/linglong_control"
export PYTHONPATH="$pkg:/mnt/d/Desktop/linglong_1025_2/ros2_ws/.test-deps${PYTHONPATH:+:$PYTHONPATH}"
python3 -m pytest -q "$pkg/test" --disable-warnings
python3 -m compileall -q "$pkg/linglong_control_tools" "$pkg/launch"
