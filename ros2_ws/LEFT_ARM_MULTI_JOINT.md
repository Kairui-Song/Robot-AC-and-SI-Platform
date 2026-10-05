# 四关节左臂统一入口

本轮将动作接到已有 `linglong_control` 多关节控制链：

`left_arm_motion → FollowJointTrajectory → arm_trajectory_controller → SimSystem / LeftArmSystem → 四关节 PDO domain`

固定顺序：`joint_1/2/3/5 → p1/p2/p3/p5`。不调用 JE p0 单电机程序，也不并行调用旧 CLI/SDO 动作脚本。
`left_arm.launch.py` 复用 `control.launch.py`；只启动控制栈，不自动执行动作。

## Ubuntu 24.04 / Jazzy 模拟命令

以下为后续手动执行命令，本轮未运行 ROS。将更新后的工程同步到虚拟机，在实际项目的 `ros2_ws` 目录运行；无需安装新环境。

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
ros2 launch linglong_control left_arm.launch.py backend:=mock
```

第二终端，在同一个 `ros2_ws` 目录：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run linglong_control system_client ready
ros2 run linglong_control system_client enable
ros2 run linglong_control left_arm_motion --wave --duration 6
```

或发送相对当前位置的四关节偏移（rad），等上一个动作完成后执行：

```bash
ros2 run linglong_control left_arm_motion --offsets 0.02 -0.02 0.01 -0.01 --duration 6
```

wave 沿用 `controller/dance_flow.sh` 的四轴相位与幅度比例，改为从新鲜反馈出发的弧度轨迹，带平滑幅度包络，末点回到起始姿态。offsets 末点保持偏移后的姿态。两者都一次提交四关节，不逐电机下发。
规划器检查全部离散位置和线性插值速度；未实现碰撞检查或加速度/jerk 限制。运动前要求正确后端、健康激活反馈和低关节速度；异常时尝试取消已接受目标。取消确认不是物理急停证明。

## EtherCAT 接口

物理后端仍使用已有 `backend:=ethercat_left_arm` 和经现场确认的 `hardware_config`，构建需要已有 IgH 开发环境及 `-DLINGLONG_WITH_IGH=ON`。动作客户端物理模式还需显式传入 `--backend ethercat_left_arm --hardware-config <同一配置文件>`；默认 mock 不接受物理反馈。
模板继续保留未确认标记，不能直接用作现场标定。参见 [接入要求](LEFT_ARM_HARDWARE.md)。本轮没有运行物理模式。

新增 `ethercat_bus` 和 `ethercat_slave_1/2/3/5` 状态资源，由 joint_state_broadcaster 进入 `/dynamic_joint_states`，再传给诊断及 fault_snapshot JSON。两个后端在原八字段健康接口上增加 `hardware_state`、`transition_sequence`、`commands_enabled`，供系统状态机确认生命周期和命令所有权。
字段定义见 [接口说明](../docs/ethercat/INTERFACES.md)。这些是插件报告的数据，不是独立硬件测量或实机验收证据。
控制循环故障后 ROS 状态流可能停止，最后一次故障帧不保证被发布；生命周期错误日志同时记录锁存故障码、站号及 WKC。恢复仍需排查原因、重启并重新确认，不自动恢复旧轨迹。

DC 时间基准、现场 PDO 导出、制动与急停行为、新插件完整 ROS 构建/Action/lifecycle 联调、真机闭环仍待各自完成；本轮不据离线测试宣称工业级验收通过。
