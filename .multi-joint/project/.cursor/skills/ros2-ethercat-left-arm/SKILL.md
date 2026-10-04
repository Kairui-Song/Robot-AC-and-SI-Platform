---
name: ros2-ethercat-left-arm
description: Maintains Linglong four-joint ROS2 and EtherCAT control integration. Use when explicitly requested to extend left-arm trajectories, IgH diagnostics, CiA402 fault handling, or the multi-joint control entry point.
disable-model-invocation: true
---

# 左臂 ROS2 + EtherCAT 工程维护

1. 先定位实际项目根目录，读取 `docs/ethercat/README.md`、`INTERFACES.md`、`ROADMAP.md` 及 `ros2_ws/VERIFICATION.md`。保留已有修改。
2. 左臂固定为 joint_1/2/3/5 → p1/p2/p3/p5。沿用 `linglong_control` 的整组 Action、控制器和 `LeftArmSystem`；JE p0 单电机程序不是整臂入口。
3. 新动作接入 `/arm_trajectory_controller/follow_joint_trajectory`，一次提交全部四关节。基于新鲜反馈生成 rad 目标，检查关节限位、速度和后端，不直接复用旧脚本绝对编码器值。
4. 修改 EtherCAT 接口时同时更新 C++ 导出、Python URDF 生成、诊断字段与离线测试。原始 AL/WKC/CiA402 数据必须携带有效性信息；不完整报文不作为有效关节反馈。
5. 保留首错和整组失能语义。缺少逐站证据时故障站为 -1。禁止把自动复位、恢复旧目标或盲目重新使能作为普通修复。
6. 按用户当前授权决定验证范围。默认不安装环境、不连接实机、不运行运动；使用已有工具完成相关离线检查，并提供 Ubuntu 24.04/Jazzy 命令。用户另有明确要求时遵从其范围。
7. 交付代码和使用说明，分别记录源码实现、离线测试、ROS 运行时和实机闭环证据。不能把旧 arm_control mock 记录算作新插件的验证。

## 常用入口

- `ros2_ws/src/linglong_control/launch/left_arm.launch.py`：默认 mock，复用主启动链。
- `linglong_control_tools/left_arm_motion_plan.py`：纯函数四关节轨迹规划。
- `linglong_control_tools/left_arm_motion.py`：Action 客户端。
- `include/linglong_control/left_arm_bus.hpp`：IgH/PDO 适配。
- `include/linglong_control/left_arm_core.hpp`：整组状态与命令保护。
- `src/left_arm_system.cpp`：ros2_control 生命周期、读写、接口导出。

以上包内路径均相对于 `ros2_ws/src/linglong_control/`。操作示例见项目 `ros2_ws/LEFT_ARM_MULTI_JOINT.md`。
