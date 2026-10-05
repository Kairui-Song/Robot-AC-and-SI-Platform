# 现有左臂接入昨天的 ros2_control 控制栈

实际工程位于 `D:\Desktop\linglong_1025_2`。本次从当前任务的 C 盘工作区开发验证后，将改动同步至 D 盘工程。

## 接入关系

`FollowJointTrajectory → arm_trajectory_controller → LeftArmSystem → IgH 同一 PDO domain → 左臂 p1/p2/p3/p5`

反馈按同一组关节返回 `joint_state_broadcaster`、`/joint_states`、`/dynamic_joint_states` 和 `/diagnostics`。
沿用昨天的 `linglong_control`、`joint_1/2/3/5`、控制器配置和 Action 地址：
`/arm_trajectory_controller/follow_joint_trajectory`。

现场依据是项目原有 `controller/ethercat_left_arm_test.py`、`controller/dance_flow.sh`：
主站 0，左臂从站 1/2/3/5，EYOU 身份 0x1097/0x2406，CSP 模式 8。
本次没有使用 JE 单电机从站 0 的驱动身份或 PDO 布局。

现有左臂 shell/Python 文件通过 EtherCAT CLI 做 SDO 点动/动作测试。本插件复用其从站及对象字典约定，
新增周期 PDO 后端，**不在 ROS 控制周期中启动这些脚本**。四关节目标经过整组校验后才写入过程映像并发送。
原脚本的固定波浪动作没有自动移植为启动动作；应用应通过已有 Action 提交整臂轨迹。

## 构建

在连接 EtherCAT 的 Ubuntu/Jazzy 主控上安装 IgH 开发头文件和 `libethercat`，然后：

```bash
source /opt/ros/jazzy/setup.bash
cd /path/to/linglong_1025_2/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to linglong_control \
  --cmake-args -DLINGLONG_WITH_IGH=ON
source install/setup.bash
```

非标准安装可传 `-DIGH_INCLUDE_DIR=/path/to/include -DIGH_LIBRARY=/path/to/libethercat.so`。
没有 IgH 时正常构建仍只安装模拟插件；选择物理后端会报插件不存在，绝不会自动退回模拟。
使用 IgH 1.6 官方公共头文件完成了适配器编译/假总线测试，主控实际版本仍需本机构建验证。

## 填写现场配置

复制 `src/linglong_control/config/left_arm_hardware.yaml` 为主控现场配置。
模板默认不能启用硬件：三个确认标志为 false，位置/速度标定和看门狗间隔为 0。

- 每关节填写带方向的 `counts_per_radian`、`zero_counts`、`velocity_counts_per_rad_s`。速度对象的实际单位须单独确认，不能默认等于位置计数单位。
- 填写关节上下限、最大指令速度、每周期最大步长和跟随误差。
- 设置主控周期、DC AssignActivate 和驱动看门狗。`dc_assign_activate: 0` 表示关闭 DC，模板不猜测现场参数。PDO 周期与 controller_manager 的 `update_rate` 使用同一配置。
- 验证驱动在失能、断网、进程退出和看门狗到期时的制动/重力负载行为，然后设置 `stop_behavior_confirmed`。
- 校准与实际 PDO 映射确认后，设置对应确认标志。

插件在配置时读取设备身份及 PDO 布局，不重写 SII 映射。要求 SM2 输出含
`0x607a:00/int32`、`0x6040:00/uint16`，SM3 输入含 `0x6064:00/int32`、
`0x606c:00/int32`、`0x6041:00/uint16`、`0x6061:00/int8`。
可选 `0x6060:00/int8` 输出会每周期写 8；标准目标速度/转矩和位置/速度/转矩偏置输出保持零。
未知输出对象、错误位宽/方向、重复必要对象、缺少模式反馈会拒绝配置。
**尚未取得现场 PDO 导出文件；不能保证现有 SII 已包含这些条目。**

机械模型仍是原来的示意 URDF；关节数与接口匹配，不代表已完成机械几何、碰撞或动力学标定。

## 启动与状态查看

先结束旧 ROS SDO 节点、网页左臂动作和单电机测试，避免其他进程操作同一主站。
IgH master reservation 仅排斥其他申请独占主站的应用，不能替代对 EtherCAT CLI/网页命令的运行管理。
本次未自动连接主控或执行任何实机动作。

```bash
ros2 launch linglong_control control.launch.py \
  backend:=ethercat_left_arm \
  hardware_config:=/absolute/path/to/left_arm_calibrated.yaml rviz:=false
```

该启动只配置硬件并建立禁用驱动的周期通信；等待 `/system/state` 为 READY 后，显式执行 `ros2 run linglong_control system_client enable` 或在网页点击使能，才执行四关节 CiA402 使能流程。激活时目标先对齐各关节实测位置，
所有关节均进入 CSP/Operation Enabled 才允许控制器执行指令，不自动复位驱动故障。
原 `trajectory_demo` 和故障注入实验仍只允许 MOCK，不能用作实机验收工具。

```bash
ros2 control list_hardware_components
ros2 control list_hardware_interfaces
ros2 control list_controllers
ros2 run linglong_control fault_snapshot --backend ethercat_left_arm \
  --nominal-period 0.01 --duration 3 --output left-arm-snapshot.json
```

修改周期时同步调整快照的 `--nominal-period`。诊断节点由 launch 自动获得实际周期和后端。
默认模拟入口仍是 `ros2 launch linglong_control control.launch.py backend:=mock`。

## 停止、故障及验证边界

轨迹控制器停用：保持当前反馈位置，释放整组控制接口；重新取得接口时丢弃旧目标。
硬件停用：对四关节发送 controlword 0。WKC 不完整、掉线、模式/状态异常、越界、
速度/步长/跟随误差超限和活动周期超时都会锁存故障并尝试整组失能，返回 ERROR。
故障后即使 lifecycle cleanup 也不自动清除，需排除原因后重启。
发送成功只表示请求已交给总线，不表示电机已完成停机；失联时依赖已确认的驱动看门狗与制动措施。

2026-09-26 离线结果：112 项 Python 回归、5 项 CTest 通过。
其中新增 C++ 核心测试覆盖四关节启停、方向/零位、整组命令校验、故障锁存；
PDO 适配器测试使用官方 IgH 1.6 头文件及假传输，覆盖同批发送、读回、WKC/发送失败、身份/布局拒绝。
这不等于 ROS 插件完整构建成功，也不等于真机闭环或实时性验收。
当前环境缺少 ROS Jazzy 与 IgH 库；完整 colcon 构建、生命周期/Action 联调、现场 PDO 和负载停机验证仍待主控执行。

参考接口：[ROS 2 Jazzy SystemInterface](https://control.ros.org/jazzy/doc/api/classhardware__interface_1_1SystemInterface.html)、
[IgH 官方应用 API](https://docs.etherlab.org/ethercat/1.6/doxygen/group__ApplicationInterface.html)。
