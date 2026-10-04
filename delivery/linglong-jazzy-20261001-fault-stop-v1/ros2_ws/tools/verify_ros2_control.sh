#!/usr/bin/env bash
# Run on Ubuntu 24.04 + ROS 2 Jazzy. Starts ONLY the mock stack.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo 'ROS 2 Jazzy is required.' >&2
  exit 1
fi
source /opt/ros/jazzy/setup.bash
# Separate this simulation from other robot applications on the host.
export ROS_DOMAIN_ID="${LINGLONG_TEST_DOMAIN_ID:-87}"
export ROS_LOCALHOST_ONLY=1
mkdir -p verification
records="$(mktemp -d "verification/$(date +%Y%m%d-%H%M%S)-XXXXXX")"
records="$(realpath "$records")"
exec > >(tee "$records/session.log") 2>&1
phase=environment
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
finish() {
  local status=$?
  trap - EXIT
  cleanup
  python3 - "$records" "$phase" "$status" <<'PY'
import json, pathlib, sys
path, phase, code = sys.argv[1:]
pathlib.Path(path, 'result.json').write_text(json.dumps({
    'scope': 'linglong_control ROS 2 Jazzy MOCK runtime; no physical EtherCAT',
    'passed': int(code) == 0, 'last_phase': phase, 'exit_code': int(code),
}, indent=2) + '\n')
PY
  echo "Verification exit=$status phase=$phase records=$records"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cat /etc/os-release > "$records/os-release.txt"
uname -a > "$records/kernel.txt"
dpkg-query -W 'ros-jazzy-*' > "$records/ros-packages.txt"
python3 - "$records" <<'PY'
import hashlib, json, pathlib, sys
files = [p for p in pathlib.Path('src').rglob('*') if p.is_file()
         and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts]
pathlib.Path(sys.argv[1], 'source-sha256.json').write_text(json.dumps({
    str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)
}, indent=2) + '\n')
PY
phase=build
colcon build --symlink-install --packages-up-to linglong_control \
  --cmake-args -DLINGLONG_CORE_ONLY=OFF -DLINGLONG_WITH_IGH="${LINGLONG_WITH_IGH:-OFF}" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
source install/setup.bash
phase=package_tests
colcon test --packages-select linglong_control arm_control --event-handlers console_direct+
colcon test-result --verbose | tee "$records/package-tests.txt"
start_mock() {
  local logfile="$1"
  shift
  setsid ros2 launch linglong_control control.launch.py rviz:=false "$@" >"$logfile" 2>&1 &
  launch_pid=$!
  timeout 55 ros2 run linglong_control system_transition ready
  timeout 55 ros2 run linglong_control system_transition enable
}
start_mock "$records/launch.log"

# The client has bounded discovery, feedback, Action and completion timeouts.
phase=trajectory
timeout 35 ros2 run linglong_control trajectory_demo 2>&1 | tee "$records/trajectory.log"
phase=cancel
timeout 35 ros2 run linglong_control trajectory_demo --cancel 2>&1 | tee "$records/cancel.log"
phase=restart
timeout 35 ros2 run linglong_control architecture_probe restart 2>&1 | tee "$records/restart.log"
timeout 10 ros2 control list_controllers | tee "$records/controllers.txt"
timeout 10 ros2 control list_hardware_components | tee "$records/hardware.txt"
timeout 10 ros2 control list_hardware_interfaces | tee "$records/interfaces.txt"
timeout 10 ros2 topic echo /diagnostics --once >"$records/diagnostics.yaml"
phase=reactivation
timeout 35 ros2 run linglong_control trajectory_demo 2>&1 | tee "$records/reactivation.log"
timeout --kill-after=3s 15s ros2 run linglong_control fault_snapshot \
  --duration 1 --output "$records/normal-evidence.json" >"$records/normal-evidence.log" 2>&1
cleanup
phase=dropout
start_mock "$records/dropout-launch.log" dropout_after_cycles:=1500
timeout --kill-after=3s 40s ros2 run linglong_control fault_snapshot \
  --duration 30 --until-fault --output "$records/dropout-evidence.json" >"$records/dropout-evidence.log" 2>&1 &
snapshot_pid=$!
timeout 55 ros2 run linglong_control architecture_probe fault \
  --fault-log "$records/dropout-launch.log" --expected-code 6 2>&1 | tee "$records/dropout.log"
wait "$snapshot_pid"
snapshot_pid=''
cleanup
phase=injected_fault
start_mock "$records/fault-launch.log" fault_after_cycles:=1500
timeout --kill-after=3s 40s ros2 run linglong_control fault_snapshot \
  --duration 30 --until-fault --output "$records/fault-evidence.json" >"$records/fault-evidence.log" 2>&1 &
snapshot_pid=$!
timeout 55 ros2 run linglong_control architecture_probe fault \
  --fault-log "$records/fault-launch.log" --expected-code 7 2>&1 | tee "$records/fault.log"
wait "$snapshot_pid"
snapshot_pid=''
phase=complete
echo "Mock trajectory, cancellation, controller restart and fault propagation passed. Records: $records"
