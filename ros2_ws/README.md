# ROS2 工作空间入口

当前主线为 Ubuntu 24.04 / Jazzy 的 `linglong_control` 标准控制链：

- [Web、系统状态机与 ros2_control 接入](WEB_CONTROL.md)：当前启动默认 READY，显式使能后发送轨迹。

- [四关节运行入口](LEFT_ARM_MULTI_JOINT.md)
- [系统接口、QoS、参数、时间与并发约定](SYSTEM_CONTRACT.md)
- [rosbag2 自动录制、归档、分析与回放验收](BAG_WORKFLOW.md)
- [分层验证记录](VERIFICATION.md)

以下保留旧 `arm_control` 单点演示，不能将其运行记录替代新栈的验收。

> 昨天的 ros2_control 控制栈已增加可选左臂四关节 PDO 后端：见 [LEFT_ARM_HARDWARE.md](LEFT_ARM_HARDWARE.md)。入口仍为 `ros2 launch linglong_control control.launch.py`，默认 mock；物理后端需现场标定并单独编译。模拟架构见 [ROS2_CONTROL.md](ROS2_CONTROL.md)。以下保留旧单点 SDO 演示，两套 launch 不应同时运行。

包名 `arm_control`，目标环境 Ubuntu 22.04 + ROS2 Humble。源码、参数、launch、RViz 和示意 URDF 全部在 `src/arm_control`，可独立复制到 ROS2 工作空间，无需 Flask、SSH 或原项目的 Python 路径。

## 接口与范围

- 订阅 `/joint_command`：`trajectory_msgs/msg/JointTrajectory`。四个关节 `joint_1/2/3/5` 必须各出现一次，顺序任意，位置单位 rad。
- 最小实现仅接受一个立即执行的点，`time_from_start=0`，不接受速度、加速度、力矩、多点轨迹或未来调度；不实现 FollowJointTrajectory action、插值、MoveIt 或 ros2_control。
- 发布 `/joint_states`：`sensor_msgs/msg/JointState`，硬件模式从 `0x6064` 读取实际位置，转换为 rad。读取失败不发布假数据；velocity、effort 留空。
- `robot_state_publisher` 根据反馈发布 TF，RViz 显示示意模型。不要同时启动另一个 joint_state_publisher 覆盖反馈。
- mock 模式只是即时位置模拟，用于验证 ROS 接口与可视化，不能证明实机控制。

## 1. 构建和模拟运行

在已安装 ROS2 Humble 的 Ubuntu 终端执行（首次使用 rosdep 需按 ROS 官方安装说明完成初始化）：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/linglong_1025_2/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select arm_control
source install/setup.bash
ros2 launch arm_control arm_control.launch.py
```

另开终端，同样 source ROS 和工作空间后，持续发送小角度目标：

```bash
ros2 topic pub --rate 5 /joint_command trajectory_msgs/msg/JointTrajectory \
  '{joint_names: [joint_1, joint_2, joint_3, joint_5], points: [{positions: [0.03, -0.03, 0.02, 0.01]}]}'
```

第三个终端观察：

```bash
ros2 topic echo /joint_states --once
ros2 topic hz /joint_states
ros2 run tf2_ros tf2_echo base_link link_5
```

RViz 应显示四个关节对应的姿态变化。Ctrl+C 停止发指令，约 2 秒后节点锁存超时故障；重新启动节点才能接受指令。无桌面环境可加 `rviz:=false`。指令使用 depth=1、volatile QoS；非零 header 时间戳要求不超过 0.5 秒且不在未来，零时间戳表示收到即执行。

## 2. 真机标定与运行

代码复用 `controller/ethercat_left_arm_test.py` 和 `controller/dance_flow.sh` 的协议：主站 0，从站 1、2、3、5；`download ... 0x607a 0x00 -t int32` 下发，`upload ... 0x6064 0x00 -t int32` 读回。不直接启动原测试脚本，避免它们的自动动作、回原位和失能流程与 ROS 节点冲突。

1. 在 EtherCAT 主控本机部署本包并构建。必须独占这些从站，停止网页动作、dance 和其他写目标的程序；当前最小节点不提供跨进程互斥。
2. 复制 `src/arm_control/config/arm_control.yaml` 为现场参数文件。按关节 1/2/3/5 顺序填写实测 `counts_per_radian`、`zero_counts`、机械范围 `lower_limits/upper_limits`。示例数值不能用于实机。转换公式为 `counts = zero + rad × counts_per_radian`；减速比与编码器分辨率必须以驱动器实际位置单位为准，方向反向时比例为负。零点是已标定参考姿态的计数，不是每次启动位置。
3. 标定确认后将 `calibration_confirmed` 设为 `true`。默认 `max_step_rad=0.05` 限制每次目标相对当前反馈的距离，**不是速度/加速度限制**，不会生成平滑轨迹。
4. 按已有现场调试流程完成从站 OP、CSP 模式（6061=8）及使能（6041 & 006f = 0027），确保有效周期通信和目标保持已就绪。此节点不会自动初始化、复位或使能驱动；原点动测试结束会失能，不能把它当常驻初始化服务。
5. 运行账户必须具备 EtherCAT CLI 所需设备权限。节点不调用 sudo、不保存密码。先用同一账户执行 `ethercat -m 0 upload -p 1 0x6064 0x00 -t int32` 验证可读。
6. 用实际参数路径启动：

```bash
ros2 launch arm_control arm_control.launch.py \
  backend:=ethercat params_file:=/absolute/path/to/hardware.yaml rviz:=false
```

首次先查看 `/joint_states`，根据当前反馈计算四关节的小幅目标；不要把模拟示例的绝对角度直接发到真机。现场急停可用并支撑机械臂，因为软件失能可能导致重力下落。

收到指令后检查驱动状态，开始周期刷新目标和读取反馈。命令超时、状态异常、通信异常或正常退出时，对已接管的四个从站尝试写 `6040=0`。发生故障后锁存，不自动恢复。未收到指令前节点只读反馈，退出不改变现场使能状态。

CLI/SDO 是逐轴串行、非实时接口，默认轮询仅 5 Hz，实际频率取决于命令耗时；不是 1 kHz CSP 控制器，也不保证四轴同步。每条 CLI 默认超时 0.5 秒，单线程中的多条阻塞命令会延后看门狗处理，失能本身也可能失败。主站周期 PDO/watchdog 与硬件急停仍由现场控制系统承担；SIGKILL 或断电无法保证软件清理。若驱动要求严格周期 CSP，应将本适配层换为已有实时 PDO 控制器的接口。

URDF 的杆长、旋转轴、范围均为示意，不代表真实机械结构；实机精确可视化需替换为实测或 CAD 导出的模型并同步限位。

## 3. 测试与验收

不装 ROS 也能测试转换、指令校验、命令构造、回调中的看门狗和故障处理：

```bash
cd ros2_ws/src/arm_control
python3 -m pip install pytest
PYTHONPATH=. python3 -m pytest test -q
```

ROS 环境构建后执行 `colcon test --packages-select arm_control` 和 `colcon test-result --verbose`。回调单测使用轻量 ROS 替身，不验证 DDS、launch 或 RViz；仍需按上面的终端命令完成集成验收。

验收记录应包含：ROS 版本、mock/ethercat 模式、topic echo/hz 输出、RViz 截图、四关节目标与实际反馈、停止发送后的故障日志、现场标定参数。真机完成上述记录前，不应声称“已完成硬件闭环联调”。

## 4. 面试讲解和简历

阅读顺序：`backend.py`（弧度换算和命令协议）→ `node.py`（订阅、校验、反馈、看门狗）→ YAML（参数）→ launch（节点组合）→ URDF/RViz（TF 与可视化）。

源码完成阶段可写：

> 基于现有 EtherCAT 命令行控制开发 ROS2 机械臂节点，设计单点 JointTrajectory 指令与 JointState 反馈接口，实现位置标定转换、参数化启动及 RViz 示意模型，并编写控制逻辑单元测试。

实际运行验收后再补充“完成 ROS2/RViz 联调”；实机记录齐全后再补充“四关节实机位置指令下发与反馈验证”。不要写成完整轨迹跟踪或实时运动控制系统。

参考：[ROS2 Python 参数与 launch](https://docs.ros.org/en/humble/Tutorials/Beginner-Client-Libraries/Using-Parameters-In-A-Class-Python.html)、[robot_state_publisher 的 JointState/URDF 接口](https://index.ros.org/p/robot_state_publisher/)。
# 左臂整组 ros2_control 后端（2026-09-26）

昨天的 `linglong_control` 现增加可选 `LeftArmSystem` IgH PDO 插件，对接原有左臂从站 1/2/3/5。
沿用整组 FollowJointTrajectory 接口。构建、现场标定、启动及验证边界见 [LEFT_ARM_HARDWARE.md](LEFT_ARM_HARDWARE.md)。
本文旧 `arm_control` 说明仍对应独立的低频 SDO 演示。

