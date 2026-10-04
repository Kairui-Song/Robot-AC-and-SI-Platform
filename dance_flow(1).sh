cat > dance_flow.sh << 'EOF'
#!/bin/bash

echo "=== 丝滑波浪联动 ==="
echo "按 Ctrl+C 停止"

# 使能所有关节
for i in 1 2 3 5; do
    sudo ethercat -m0 download -p $i 0x6040 0x00 -t uint16 15 2>/dev/null
done

# ========== 参数 ==========
# 每个关节的基础位置（零点附近）
BASE1=300000
BASE2=200000
BASE3=100000
BASE5=50000

# 每个关节的振幅
AMP1=200000
AMP2=150000
AMP3=100000
AMP5=60000

# 每个关节的相位偏移（形成波浪）
PHASE1=0
PHASE2=1.2
PHASE3=2.4
PHASE5=3.6

# ========== 主循环 ==========
step=0
while true; do
    # 连续相位
    phase=$(echo "scale=4; $step * 0.04" | bc)
    
    # 用 bc 计算正弦（如果支持）
    sin1=$(echo "scale=4; s($phase + $PHASE1)" | bc -l 2>/dev/null)
    sin2=$(echo "scale=4; s($phase + $PHASE2)" | bc -l 2>/dev/null)
    sin3=$(echo "scale=4; s($phase + $PHASE3)" | bc -l 2>/dev/null)
    sin5=$(echo "scale=4; s($phase + $PHASE5)" | bc -l 2>/dev/null)
    
    # 如果 bc -l 不支持，用近似
    if [ -z "$sin1" ]; then
        # 多项式近似
        x=$(echo "scale=4; $phase - 6.2832 * ($phase / 6.2832 | bc)" | bc 2>/dev/null)
        if [ -z "$x" ]; then x=0; fi
        x2=$(echo "scale=4; $x * $x" | bc 2>/dev/null)
        x3=$(echo "scale=4; $x2 * $x" | bc 2>/dev/null)
        x5=$(echo "scale=4; $x3 * $x2" | bc 2>/dev/null)
        sin1=$(echo "scale=4; $x - $x3/6 + $x5/120" | bc 2>/dev/null)
        if [ -z "$sin1" ]; then sin1=0; fi
        # 根据相位取反
        p=$(echo "$phase / 6.2832" | bc)
        if [ $((p % 2)) -eq 1 ]; then
            sin1=$(echo "scale=4; -$sin1" | bc 2>/dev/null)
        fi
        sin2=$sin1
        sin3=$sin1
        sin5=$sin1
    fi
    
    # 计算位置
    POS1=$(echo "scale=0; $BASE1 + $AMP1 * $sin1" | bc 2>/dev/null | cut -d. -f1)
    POS2=$(echo "scale=0; $BASE2 + $AMP2 * $sin2" | bc 2>/dev/null | cut -d. -f1)
    POS3=$(echo "scale=0; $BASE3 + $AMP3 * $sin3" | bc 2>/dev/null | cut -d. -f1)
    POS5=$(echo "scale=0; $BASE5 + $AMP5 * $sin5" | bc 2>/dev/null | cut -d. -f1)
    
    # 安全值
    [ -z "$POS1" ] && POS1=$BASE1
    [ -z "$POS2" ] && POS2=$BASE2
    [ -z "$POS3" ] && POS3=$BASE3
    [ -z "$POS5" ] && POS5=$BASE5
    
    # 同时发送所有关节
    sudo ethercat -m0 download -p 1 0x607a 0x00 -t int32 $POS1 2>/dev/null
    sudo ethercat -m0 download -p 2 0x607a 0x00 -t int32 $POS2 2>/dev/null
    sudo ethercat -m0 download -p 3 0x607a 0x00 -t int32 $POS3 2>/dev/null
    sudo ethercat -m0 download -p 5 0x607a 0x00 -t int32 $POS5 2>/dev/null
    
    # 每20步打印
    if [ $((step % 20)) -eq 0 ]; then
        echo "位置: 关1=$POS1 关2=$POS2 关3=$POS3 关5=$POS5"
    fi
    
    sleep 0.03
    step=$((step + 1))
done
EOF

chmod +x dance_flow.sh
./dance_flow.sh
