#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import argparse
import numpy as np
from motor_controller import MotorController

class LeftArmMotionPlayer:
    """左臂动作播放器"""
    
    def __init__(self, motor_controller):
        self.motor = motor_controller
    
    def bezier_interpolate(self, p0, p1, p2, p3, t):
        """三次贝塞尔曲线插值"""
        t = np.clip(t, 0.0, 1.0)
        mt = 1.0 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        t2 = t * t
        t3 = t2 * t
        return mt3 * p0 + 3 * mt2 * t * p1 + 3 * mt * t2 * p2 + t3 * p3
    
    def interpolate_keyframes(self, keyframes, target_time, loop=False, total_time=None):
        """在关键帧之间进行插值"""
        if len(keyframes) == 0:
            return None
        
        if len(keyframes) == 1:
            return keyframes[0][1].copy()
        
        cumulative_times = [0.0]
        for i in range(len(keyframes) - 1):
            cumulative_times.append(cumulative_times[-1] + keyframes[i][0])
        
        if loop and total_time is not None:
            cumulative_times.append(total_time)
        
        if loop and total_time is not None and total_time > 0:
            target_time = target_time % total_time
        
        if target_time <= 0:
            return keyframes[0][1].copy()
        
        num_segments = len(cumulative_times) - 1
        for i in range(num_segments):
            t_start = cumulative_times[i]
            t_end = cumulative_times[i + 1]
            
            if t_start <= target_time <= t_end:
                t = (target_time - t_start) / (t_end - t_start) if t_end > t_start else 0.0
                
                start_idx = i
                if i == num_segments - 1 and loop:
                    end_idx = 0
                else:
                    end_idx = i + 1
                
                if i == 0:
                    prev_idx = len(keyframes) - 1 if loop else 0
                else:
                    prev_idx = i - 1
                
                if i == num_segments - 1 and loop:
                    next_idx = 1
                else:
                    next_idx = min(len(keyframes) - 1, i + 2)
                
                result = np.zeros(7)
                
                for joint_idx in range(7):
                    p0 = keyframes[prev_idx][1][joint_idx]
                    p1 = keyframes[start_idx][1][joint_idx]
                    p2 = keyframes[end_idx][1][joint_idx]
                    
                    if i == num_segments - 1 and loop:
                        p3 = keyframes[1][1][joint_idx] if len(keyframes) > 1 else p2
                    else:
                        p3 = keyframes[next_idx - 1][1][joint_idx] if next_idx < len(keyframes) else p2
                    
                    if (i == 0 and not loop) or (i == num_segments - 1 and loop and start_idx == len(keyframes) - 1):
                        cp1 = p1
                        cp2 = p1 + (p2 - p1) * 0.33
                    elif (i == num_segments - 1 and not loop) or (i == num_segments - 1 and loop):
                        cp1 = p1 + (p2 - p0) * 0.33
                        cp2 = p2
                    else:
                        tangent1 = (p2 - p0) * 0.5
                        tangent2 = (p3 - p1) * 0.5
                        cp1 = p1 + tangent1 * 0.33
                        cp2 = p2 - tangent2 * 0.33
                    
                    result[joint_idx] = self.bezier_interpolate(p1, cp1, cp2, p2, t)
                
                return result.tolist()
        
        return keyframes[-1][1].copy()
    
    def play(self, loop=False, fps=50):
        """播放左臂动作"""
        # 左臂关键帧: (持续时间, [7个关节角度])
        left_arm_keyframes = [
            (1.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            (2.0, [-0.5, 0.8, -0.6, 0.8, 0.5, -0.8, 0.6]),
            (1.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            (2.0, [0.5, -0.8, 0.6, -0.8, -0.5, 0.8, -0.6]),
            (1.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            (1.5, [-0.8, 1.2, -1.0, 1.2, 0.9, -1.3, 1.2]),
            (1.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]
        
        left_arm_keyframes_np = [(dur, np.array(angles)) for dur, angles in left_arm_keyframes]
        
        if loop:
            total_time = sum(dur for dur, _ in left_arm_keyframes_np)
        else:
            total_time = sum(dur for dur, _ in left_arm_keyframes_np[:-1])
        
        print(f"✔ 左臂控制测试 - 串口模式")
        print(f"✔ 关键帧数: {len(left_arm_keyframes_np)}")
        print(f"✔ 总时长: {total_time:.2f} 秒")
        print(f"✔ 模式: {'循环' if loop else '单次'}")
        print(f"✔ 帧率: {fps} Hz")
        print("")
        print("按 Ctrl+C 停止")
        
        period = 1.0 / fps
        frame_count = 0
        frame_time = 0.0
        
        try:
            while True:
                while True:
                    if not loop and frame_time > total_time:
                        break
                    
                    frame_start = time.time()
                    actual_time = frame_time % total_time if (loop and total_time > 0) else frame_time
                    
                    arm_angles = self.interpolate_keyframes(
                        left_arm_keyframes_np, actual_time,
                        loop=loop, total_time=total_time
                    )
                    
                    if arm_angles is not None:
                        # 发送到电机
                        self.motor.set_left_arm(arm_angles)
                        
                        if frame_count % (fps // 2) == 0:
                            angles_str = " ".join([f"{a:.3f}" for a in arm_angles])
                            print(f"[{frame_count:04d}] t={actual_time:.2f}s 左臂: [{angles_str}]")
                        
                        frame_count += 1
                    
                    elapsed = time.time() - frame_start
                    sleep_time = period - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    
                    frame_time += period
                
                if not loop:
                    break
                frame_time = 0.0
                print("🔄 重新播放...")
        
        except KeyboardInterrupt:
            print("\n🛑 停止播放")

def main():
    parser = argparse.ArgumentParser(description="左臂控制测试 - 串口模式")
    parser.add_argument("-p", "--port", help="串口端口号 (例如: COM3, /dev/ttyUSB0)")
    parser.add_argument("-b", "--baudrate", type=int, default=115200, help="波特率 (默认: 115200)")
    parser.add_argument("-l", "--loop", action="store_true", help="循环播放")
    parser.add_argument("-f", "--fps", type=int, default=50, help="播放帧率 (默认: 50)")
    args = parser.parse_args()
    
    motor = MotorController(port=args.port, baudrate=args.baudrate)
    
    if not motor.connect():
        print("❌ 无法连接到主控")
        return
    
    try:
        player = LeftArmMotionPlayer(motor)
        player.play(loop=args.loop, fps=args.fps)
    finally:
        motor.close()

if __name__ == "__main__":
    main()