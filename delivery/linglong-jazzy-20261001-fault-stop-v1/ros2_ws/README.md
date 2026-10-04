# Linglong 四关节机械臂控制项目

主入口是 `linglong_control`，目标环境为 **Ubuntu 24.04 + ROS 2 Jazzy**。
默认运行 MOCK，提供整组 `FollowJointTrajectory`、位置/速度反馈、故障锁存和系统状态管理。
启动后进入 READY（未使能），必须显式使能才能执行轨迹。

Windows → Ubuntu 的统一发行、完整性校验和新目录部署见 [交付说明](DELIVERY.md)。
新版 MOCK 故障停用由管理器按序完成；故障保护阈值保持不变。物理后端不采用模拟的故障传输策略。

`arm_control` 保留示意 URDF/RViz 资源和独立的旧单点 SDO 演示。
旧方案的 Humble 构建说明、`/joint_command` 与 EtherCAT CLI 操作已归档至
[旧 arm_control 使用说明](LEGACY_ARM_CONTROL.md)。新旧 launch 不应同时运行。
当前新控制栈的构建与集成验证以 Jazzy 为准，不声明其他 ROS 发行版已通过验证。

## 构建与模拟运行

在已安装 Jazzy、rosdep 和 colcon 的 Ubuntu 环境执行：

```bash
source /opt/ros/jazzy/setup.bash
cd /path/to/linglong_1025_2/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
ros2 launch linglong_control control.launch.py backend:=mock rviz:=false
```

另一终端 source 同一 ROS 与工作空间后：

```bash
ros2 run linglong_control system_transition ready
ros2 run linglong_control system_transition enable
ros2 run linglong_control trajectory_demo
ros2 run linglong_control system_transition disable
ros2 topic echo /system/state --once
# 结束本次运行；SHUTDOWN 为终态：
ros2 run linglong_control system_transition shutdown
```

有桌面环境时使用 `rviz:=true`。`trajectory_demo` 仅允许 MOCK，
从当前模拟反馈生成小幅往返轨迹；不能用该示例直接控制实机。
`system_transition` 等待转换结果；直接调用 `/system/*` Trigger 服务只表示请求已接受。

## 接口与状态

- 四关节：`joint_1`、`joint_2`、`joint_3`、`joint_5`，使用 rad 与 rad/s。
- 轨迹：`/arm_trajectory_controller/follow_joint_trajectory` Action。
- 反馈：`/joint_states`、`/dynamic_joint_states`；后者包含硬件健康状态。
- 管理：`/system/state`，以及 enable、disable、recover、shutdown 服务。
- 正常流程：READY → ENABLING → ENABLED ⇄ RUNNING → STOPPING → READY。
- 故障不自动解除。MOCK 可显式 recover 回 READY；实机故障需排除原因后重启。

只读组件查询超时会清理本地待处理请求并重新查询，不使用迟到旧结果刷新状态。
生命周期请求超时先进入 FAULT，保留有限的迟到回复窗口；仍无确定结果时，
`restart_required=true` 且 `operation=null`，最近结果标记 `completion_unknown=true`。
此时拒绝新的生命周期操作，并通过 `intervention_reason` 指明处置步骤。
须先按现场独立停机流程保障机械臂，再终止整个 controller_manager/launch、排除原因并重启；
只重启 system_manager 不能排除远端迟到使能。详见 [状态与恢复协议](STATE_MACHINE.md)。

## 验证

在 Jazzy 环境执行：

```bash
bash tools/verify_state_machine.sh
```

该入口运行 Python 回归、C++/ROS 插件测试及 MOCK 状态机联调，
使用独立测试 domain 并保存结果。假 IgH 测试需要
`build-left-arm/igh-headers/ecrt.h`（官方 IgH 1.6 头文件）；该脚本不下载头文件，
缺失时需要先准备该文件，不能把缺少该测试当成实机插件通过。

验证层次应分开理解：离线单测验证逻辑，假总线验证插件行为，MOCK 联调验证 ROS 接口。
三者都不能替代真实 PDO/DC/看门狗、制动与负载停机验收。
实机插件周期读写已改为非阻塞获取生命周期锁；转换期间保留旧反馈、停止推进反馈周期计数，
由生命周期代码独占总线完成使能/失能握手。这不构成整套系统硬实时保证。

## 进一步阅读

- [新控制栈架构与 Action 验收](ROS2_CONTROL.md)
- [系统状态机、超时与恢复边界](STATE_MACHINE.md)
- [左臂 PDO 后端与现场标定](LEFT_ARM_HARDWARE.md)
- [性能与可靠性模拟验证](SIMULATION_VALIDATION.md)
- [按日期保存的验证记录](VERIFICATION.md)
- [旧 SDO 演示归档](LEGACY_ARM_CONTROL.md)
