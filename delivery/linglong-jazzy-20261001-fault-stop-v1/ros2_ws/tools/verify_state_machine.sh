#!/usr/bin/env bash
# Run inside the existing Jazzy environment. Simulation only.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID="${LINGLONG_TEST_DOMAIN_ID:-89}"
export ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$PWD/src/linglong_control:$PWD/src/arm_control:${PYTHONPATH:-}"
python3 -m pytest src/linglong_control/test src/arm_control/test tools/test_sim_validation_runner.py -q
colcon --log-base log-state-machine build --build-base build-state-machine --install-base install-state-machine \
  --packages-up-to linglong_control --cmake-args \
  -DLINGLONG_IGH_TEST_INCLUDE_DIR="$PWD/build-left-arm/igh-headers" -DCMAKE_BUILD_TYPE=Debug
source install-state-machine/setup.bash
colcon --log-base log-state-machine test --build-base build-state-machine --install-base install-state-machine \
  --packages-select linglong_control arm_control --event-handlers console_direct-
colcon test-result --test-result-base build-state-machine --verbose
python3 tools/verify_system_state.py
