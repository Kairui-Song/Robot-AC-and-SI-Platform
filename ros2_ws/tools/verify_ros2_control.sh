#!/usr/bin/env bash
# Run on Ubuntu 24.04 + ROS 2 Jazzy. Starts ONLY the mock stack.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo 'ROS 2 Jazzy is required.' >&2
  exit 1
fi
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
colcon test --packages-select linglong_control arm_control --event-handlers console_direct+
colcon test-result --verbose

# Separate this simulation from other robot applications on the host.
export ROS_DOMAIN_ID="${LINGLONG_TEST_DOMAIN_ID:-87}"
export ROS_LOCALHOST_ONLY=1
mkdir -p verification
records="$(mktemp -d "verification/$(date +%Y%m%d-%H%M%S)-XXXXXX")"
launch_pid=''
snapshot_pid=''
cleanup() {
  if [[ -n "$snapshot_pid" ]]; then
    kill -TERM "$snapshot_pid" 2>/dev/null || true
    wait "$snapshot_pid" 2>/dev/null || true
    snapshot_pid=''
  fi
  [[ -n "$launch_pid" ]] || return 0
  # Each launch owns a dedicated process group, including its ROS children.
  kill -INT -- "-$launch_pid" 2>/dev/null || true
  for ((i=0; i<50; i++)); do
    kill -0 -- "-$launch_pid" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 -- "-$launch_pid" 2>/dev/null; then
    kill -TERM -- "-$launch_pid" 2>/dev/null || true
    for ((i=0; i<30; i++)); do
      kill -0 -- "-$launch_pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL -- "-$launch_pid" 2>/dev/null || true
  fi
  wait "$launch_pid" 2>/dev/null || true
  launch_pid=''
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start_mock() {
  local logfile="$1"
  shift
  setsid ros2 launch linglong_control control.launch.py rviz:=false "$@" >"$logfile" 2>&1 &
  launch_pid=$!
}
start_mock "$records/launch.log"
timeout 55 ros2 run linglong_control system_client ready
timeout 55 ros2 run linglong_control system_client enable

# The client has bounded discovery, feedback, Action and completion timeouts.
timeout 35 ros2 run linglong_control trajectory_demo 2>&1 | tee "$records/trajectory.log"
timeout 35 ros2 run linglong_control trajectory_demo --cancel 2>&1 | tee "$records/cancel.log"
timeout 35 ros2 run linglong_control architecture_probe restart 2>&1 | tee "$records/restart.log"
timeout 10 ros2 control list_controllers | tee "$records/controllers.txt"
timeout 10 ros2 control list_hardware_components | tee "$records/hardware.txt"
timeout 10 ros2 control list_hardware_interfaces | tee "$records/interfaces.txt"
timeout 10 ros2 topic echo /diagnostics --once >"$records/diagnostics.yaml"
timeout 35 ros2 run linglong_control trajectory_demo 2>&1 | tee "$records/reactivation.log"
timeout --kill-after=3s 15s ros2 run linglong_control fault_snapshot \
  --duration 1 --output "$records/normal-evidence.json" >"$records/normal-evidence.log" 2>&1
cleanup
start_mock "$records/dropout-launch.log" dropout_after_cycles:=1500
timeout 55 ros2 run linglong_control system_client ready
timeout 55 ros2 run linglong_control system_client enable
timeout --kill-after=3s 40s ros2 run linglong_control fault_snapshot \
  --duration 30 --until-fault --output "$records/dropout-evidence.json" >"$records/dropout-evidence.log" 2>&1 &
snapshot_pid=$!
timeout 55 ros2 run linglong_control architecture_probe fault \
  --fault-log "$records/dropout-launch.log" --expected-code 6 2>&1 | tee "$records/dropout.log"
wait "$snapshot_pid"
snapshot_pid=''
cleanup
start_mock "$records/fault-launch.log" fault_after_cycles:=1500
timeout 55 ros2 run linglong_control system_client ready
timeout 55 ros2 run linglong_control system_client enable
timeout --kill-after=3s 40s ros2 run linglong_control fault_snapshot \
  --duration 30 --until-fault --output "$records/fault-evidence.json" >"$records/fault-evidence.log" 2>&1 &
snapshot_pid=$!
timeout 55 ros2 run linglong_control architecture_probe fault \
  --fault-log "$records/fault-launch.log" --expected-code 7 2>&1 | tee "$records/fault.log"
wait "$snapshot_pid"
snapshot_pid=''
echo "Mock trajectory, cancellation, controller restart and fault propagation passed. Records: $records"
