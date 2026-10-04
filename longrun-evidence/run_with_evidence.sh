#!/usr/bin/env bash
# Run from ros2_ws. Requires the previously supplied tools/longrun_vm.sh.
set -eo pipefail
bundle="$(cd "$(dirname "$0")" && pwd)"
test -f tools/longrun_vm.sh || { echo 'Run this script from ros2_ws; tools/longrun_vm.sh is required.'; exit 2; }
source /opt/ros/jazzy/setup.bash
source install-ubuntu/setup.bash
export ROS_DOMAIN_ID=42
out="$PWD/verification/evidence-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"
probe=''
runner=''
cleanup() {
  if [ -n "$runner" ]; then
    kill -TERM -- "-$runner" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$runner" 2>/dev/null || true
    wait "$runner" 2>/dev/null || true
  fi
  if [ -n "$probe" ]; then kill -TERM "$probe" 2>/dev/null || true; wait "$probe" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
{
  date -Is
  uname -a
  printenv ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_LOCALHOST_ONLY || true
  ros2 pkg prefix linglong_control
  sha256sum tools/longrun_vm.sh src/linglong_control/linglong_control_tools/{trajectory_demo,health,diagnostics}.py
  cat /proc/cpuinfo
  cat /proc/meminfo
} > "$out/environment.txt" 2>&1
python3 "$bundle/evidence_probe.py" "$out" > "$out/probe-console.log" 2>&1 &
probe=$!
for attempt in {1..30}; do
  kill -0 "$probe" 2>/dev/null || { cat "$out/probe-console.log"; exit 2; }
  [ -f "$out/probe-ready" ] && break
  sleep 1
done
test -f "$out/probe-ready" || { echo 'Evidence collector did not start'; exit 2; }
echo "Evidence: $out"
echo 'Keep terminal A running, including after a test failure.'
setsid bash tools/longrun_vm.sh > "$out/test-console.log" 2>&1 &
runner=$!
while kill -0 "$runner" 2>/dev/null; do
  if ! kill -0 "$probe" 2>/dev/null; then
    echo 'Collector stopped unexpectedly; stopping test. This run is incomplete.'
    exit 2
  fi
  tail -n 2 "$out/test-console.log"
  sleep 10
done
rc=0
wait "$runner" || rc=$?
runner=''
printf 'test_exit_code=%s\n' "$rc" > "$out/wrapper-result.txt"
echo "Test ended with code $rc; collecting scene (up to one minute)."
ps -eo pid,ppid,stat,etimes,pcpu,rss,args > "$out/processes.txt"
timeout -k 2s 12s ros2 control list_controllers > "$out/controllers.txt" 2>&1 || true
timeout -k 2s 12s ros2 topic echo /diagnostics diagnostic_msgs/msg/DiagnosticArray --filter "any(s.name == 'linglong/control' for s in m.status)" --once > "$out/diagnostics.txt" 2>&1 || true
timeout -k 2s 12s ros2 topic echo /dynamic_joint_states --once > "$out/dynamic-states.txt" 2>&1 || true
timeout -k 2s 12s ros2 topic info /dynamic_joint_states --verbose > "$out/topic-info.txt" 2>&1 || true
dmesg --ctime > "$out/kernel.txt" 2>&1 || true
tail -n 20 "$out/test-console.log"
echo "Evidence saved: $out"
echo 'Keep the original longrun result directory and terminal A launch log too.'
exit "$rc"
