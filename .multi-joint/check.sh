#!/usr/bin/env bash
set -euo pipefail
stage=/mnt/c/Users/Administrator/Desktop/linglong_1025_2/.multi-joint
pkg="$stage/project/ros2_ws/src/linglong_control"
export PYTHONPATH="$pkg:/mnt/d/Desktop/linglong_1025_2/ros2_ws/.test-deps${PYTHONPATH:+:$PYTHONPATH}"
python3 -m pytest -q "$pkg/test" --disable-warnings
cmake -S "$pkg" -B "$stage/build" -DLINGLONG_CORE_ONLY=ON -DLINGLONG_IGH_TEST_INCLUDE_DIR=/mnt/c/Users/Administrator/Desktop/linglong_1025_2/ros2_ws/build-left-arm/igh-headers
cmake --build "$stage/build" -j2
ctest --test-dir "$stage/build" --output-on-failure
