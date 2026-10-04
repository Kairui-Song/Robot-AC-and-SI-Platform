#!/usr/bin/env bash
# Invoke from ros2_ws; terminal A must already run the fresh MOCK launch.
set -eo pipefail
bundle="$(cd "$(dirname "$0")" && pwd)"
test -f tools/longrun_vm.sh || { echo 'Run from ros2_ws; tools/longrun_vm.sh is required.'; exit 2; }
test -f "${1:-}" || { echo 'Provide the current terminal A log path as argument.'; exit 2; }
launch_log="$(realpath "$1")"
source /opt/ros/jazzy/setup.bash
source install-ubuntu/setup.bash
export ROS_DOMAIN_ID=42
out="$PWD/verification/fault-trace-$(date +%Y%m%d-%H%M%S)"
instance="linglong_fault_$(date +%s)_$$"
mkdir -p "$out"
runner=''
watcher=''
finish() {
  rc=$?
  trap - EXIT INT TERM
  touch "$out/stop-request"
  if [ -n "$runner" ]; then
    kill -TERM -- "-$runner" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$runner" 2>/dev/null || true
    wait "$runner" 2>/dev/null || true
  fi
  if [ -n "$watcher" ]; then
    echo 'Freezing/extracting trace; keep this terminal open.'
    wait "$watcher" || true
  fi
  cp "$launch_log" "$out/launch.log"
  ps -eLo pid,tid,cls,rtprio,pri,stat,comm > "$out/threads-after.txt"
  if [ -f "$out/capture-complete" ]; then
    if ! trace-cmd report -i "$out/trace.dat" 2> "$out/report-errors.txt" | gzip > "$out/trace-report.txt.gz"; then
      echo 'Report conversion failed; retain trace.dat.'
      [ "$rc" -eq 0 ] && rc=2
    fi
  else
    echo 'Capture incomplete; inspect capture-error.txt and watcher.log.'
    [ "$rc" -eq 0 ] && rc=2
  fi
  printf 'exit_code=%s\n' "$rc" > "$out/result.txt"
  [ ! -f "$out/trigger.json" ] || cat "$out/trigger.json"
  echo
  echo "Result directory: $out"
  echo 'Terminal A has not been stopped. Copy this whole result directory.'
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
sudo -v
ps -eLo pid,tid,cls,rtprio,pri,stat,comm > "$out/threads-before.txt"
{
  date -Is
  uname -a
  nproc
  cat /sys/devices/system/cpu/online
  sha256sum "$bundle/freeze_on_fault.py" tools/longrun_vm.sh
} > "$out/environment.txt"
sudo -n python3 "$bundle/freeze_on_fault.py" "$launch_log" "$out" "$instance" > "$out/watcher.log" 2>&1 &
watcher=$!
for i in {1..60}; do
  [ ! -f "$out/capture-error.txt" ] || { cat "$out/capture-error.txt"; exit 2; }
  [ ! -f "$out/trigger.json" ] || { echo 'Fault already present in launch log; capturing without motion.'; exit 1; }
  [ ! -f "$out/ready" ] || break
  ps -p "$watcher" > /dev/null || { cat "$out/watcher.log"; exit 2; }
  sleep 1
done
test -f "$out/ready" || { echo 'Trace setup timed out'; exit 2; }
echo "Recording to memory; result directory: $out"
setsid timeout --signal=TERM --kill-after=10s 7200s bash tools/longrun_vm.sh > "$out/test.log" 2>&1 &
runner=$!
next_progress=$((SECONDS + 10))
while kill -0 "$runner" 2>/dev/null; do
  if [ -f "$out/trigger.json" ]; then
    echo 'Trace frozen; stopping the test.'
    exit 1
  fi
  [ ! -f "$out/capture-error.txt" ] || { cat "$out/capture-error.txt"; exit 2; }
  ps -p "$watcher" > /dev/null || { echo 'Capture helper exited unexpectedly'; exit 2; }
  if (( SECONDS >= next_progress )); then
    tail -n 2 "$out/test.log"
    next_progress=$((SECONDS + 10))
  fi
  sleep 0.2
done
rc=0
wait "$runner" || rc=$?
runner=''
exit "$rc"
