#!/usr/bin/env bash
set -eo pipefail
cd /workspace/ros2_ws
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD/src/linglong_control:$PWD/src/arm_control:${PYTHONPATH:-}"
python3 -m pytest src/linglong_control/test src/arm_control/test tools/test_sim_validation_runner.py -q
colcon --log-base log-delivery build --build-base build-delivery --install-base install-delivery \
  --packages-up-to linglong_control --cmake-args -DCMAKE_BUILD_TYPE=Debug \
  -DLINGLONG_IGH_TEST_INCLUDE_DIR="$PWD/build-left-arm/igh-headers"
source install-delivery/setup.bash
colcon --log-base log-delivery test --build-base build-delivery --install-base install-delivery \
  --packages-select linglong_control arm_control --event-handlers console_direct-
colcon test-result --test-result-base build-delivery --verbose
export ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1
python3 tools/verify_system_state.py
