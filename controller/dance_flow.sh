#!/bin/bash
# Web-triggered, bounded version of the proven dance_flow(1).sh motion.
# This script is launched as root by ethercat_bridge.py.

set -uo pipefail

MAX_STEPS="${1:-200}"
JOINTS=(1 2 3 5)

if ! [[ "$MAX_STEPS" =~ ^[0-9]+$ ]] || [ "$MAX_STEPS" -lt 1 ] || [ "$MAX_STEPS" -gt 2000 ]; then
    printf '{"event":"result","target":"left_arm","ok":false,"error":"动作步数必须在1到2000之间"}\n'
    exit 2
fi

for required_command in ethercat bc; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        printf '{"event":"result","target":"left_arm","ok":false,"error":"主控缺少命令: %s"}\n' "$required_command"
        exit 127
    fi
done

disable_all() {
    for joint in "${JOINTS[@]}"; do
        ethercat -m 0 download -p "$joint" 0x6040 0x00 -t uint16 0 >/dev/null 2>&1 || true
    done
}
trap disable_all EXIT INT TERM

for joint in "${JOINTS[@]}"; do
    if ! ethercat -m 0 download -p "$joint" 0x6040 0x00 -t uint16 15 >/dev/null; then
        printf '{"event":"result","target":"left_arm","ok":false,"error":"从站p%s使能失败"}\n' "$joint"
        exit 1
    fi
done

BASE1=300000
BASE2=200000
BASE3=100000
BASE5=50000
AMP1=200000
AMP2=150000
AMP3=100000
AMP5=60000
PHASE1=0
PHASE2=1.2
PHASE3=2.4
PHASE5=3.6

printf '{"event":"progress","stage":"dance_started","slaves":[1,2,3,5],"steps":%s}\n' "$MAX_STEPS"

step=0
while [ "$step" -lt "$MAX_STEPS" ]; do
    phase=$(echo "scale=6; $step * 0.04" | bc)
    sin1=$(echo "scale=6; s($phase + $PHASE1)" | bc -l)
    sin2=$(echo "scale=6; s($phase + $PHASE2)" | bc -l)
    sin3=$(echo "scale=6; s($phase + $PHASE3)" | bc -l)
    sin5=$(echo "scale=6; s($phase + $PHASE5)" | bc -l)

    POS1=$(echo "scale=0; $BASE1 + $AMP1 * $sin1" | bc | cut -d. -f1)
    POS2=$(echo "scale=0; $BASE2 + $AMP2 * $sin2" | bc | cut -d. -f1)
    POS3=$(echo "scale=0; $BASE3 + $AMP3 * $sin3" | bc | cut -d. -f1)
    POS5=$(echo "scale=0; $BASE5 + $AMP5 * $sin5" | bc | cut -d. -f1)

    ethercat -m 0 download -p 1 0x607a 0x00 -t int32 "$POS1" >/dev/null &&
    ethercat -m 0 download -p 2 0x607a 0x00 -t int32 "$POS2" >/dev/null &&
    ethercat -m 0 download -p 3 0x607a 0x00 -t int32 "$POS3" >/dev/null &&
    ethercat -m 0 download -p 5 0x607a 0x00 -t int32 "$POS5" >/dev/null
    if [ "$?" -ne 0 ]; then
        printf '{"event":"result","target":"left_arm","ok":false,"error":"目标位置下发失败","step":%s}\n' "$step"
        exit 1
    fi

    if [ $((step % 20)) -eq 0 ]; then
        printf '{"event":"progress","stage":"dancing","step":%s,"positions":{"1":%s,"2":%s,"3":%s,"5":%s}}\n' \
            "$step" "$POS1" "$POS2" "$POS3" "$POS5"
    fi
    sleep 0.03
    step=$((step + 1))
done

printf '{"event":"result","target":"left_arm","ok":true,"total":4,"passed":4,"failed":0,"info":"dance_flow动作完成"}\n'
