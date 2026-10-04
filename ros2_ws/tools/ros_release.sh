#!/usr/bin/env bash
# Run a command with ONLY this release and /opt/ros/jazzy in its ROS environment.
set -eo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ${LINGLONG_CLEAN_RELEASE:-} != "$root" ]]; then
  exec env -i HOME="$HOME" USER="${USER:-}" LANG=C.UTF-8 \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" \
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
    ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}" LINGLONG_CLEAN_RELEASE="$root" \
    bash "$0" "$@"
fi
cd "$root"
source /opt/ros/jazzy/setup.bash
source install-release/setup.bash
prefix="$(ros2 pkg prefix linglong_control)"
test "$prefix" = "$root/install-release/linglong_control" || {
  echo "Wrong installed package: $prefix"; exit 2;
}
cmp src/linglong_control/RELEASE_ID "$prefix/share/linglong_control/RELEASE_ID"
if [[ ${1:-} == --verify ]]; then
  python3 tools/check_release.py --installed
elif [[ ${1:-} == --record-install ]]; then
  python3 tools/check_release.py --record-install
elif [[ ${1:-} == --test ]]; then
  export ROS_DOMAIN_ID="${LINGLONG_TEST_DOMAIN_ID:-94}"
  python3 tools/verify_system_state.py
  python3 tools/verify_fault_delivery.py
elif [[ ${1:-} == --build-test ]]; then
  colcon --log-base log-release test --build-base build-release --install-base install-release \
    --packages-select linglong_control arm_control
  colcon test-result --test-result-base build-release --verbose
else
  exec ros2 "$@"
fi
