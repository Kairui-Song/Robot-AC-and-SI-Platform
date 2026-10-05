# Linglong 机器人控制系统与测试平台

以 **ROS 2 控制架构 + EtherCAT 执行器通信** 为技术主线，面向机器人关节控制、设备接入、故障定位和验证追溯。
Web/CAN/IMU 测试作为配套工具；四关节左臂是当前整臂控制对象。

## 从这里开始

- [EtherCAT 专题与代码入口](docs/ethercat/README.md)：Master/Slave、ESI、CoE、PDO/SDO、AL、WKC、DC/Sync0、CiA402、CSP、周期任务和恢复。
- [系统分层与接口约定](docs/ethercat/ARCHITECTURE.md)：ROS 轨迹如何到达各关节，谁管理总线、谁处理故障。
- [能力清单与证据边界](docs/ethercat/CAPABILITIES.md)：已有代码、已有验证和待完成项分别记录。
- [掉站诊断与恢复设计](docs/ethercat/RECOVERY.md)：已实现的故障锁存，以及尚待实现的受控恢复流程。
- [工程交付与资料规范](docs/ethercat/ENGINEERING.md)：设备资料、标定、日志、版本和阶段交付要求。
- [接口约定](docs/ethercat/INTERFACES.md)与[后续实施清单](docs/ethercat/ROADMAP.md)：统一单位、故障编号与下一阶段范围。
- [底层控制程序索引](controller/README.md)：区分单电机观察、运动实验与左臂维护脚本。

## 当前控制主线

应用提交四关节轨迹 → `arm_trajectory_controller` → `SystemInterface` → 后端 → 关节反馈与诊断。

`linglong_control/SimSystem` 用于模拟；可选 `linglong_control/LeftArmSystem` 面向 EYOU 左臂 p1/p2/p3/p5 的 IgH PDO 通信。
两个后端沿用 `joint_1/2/3/5`、position 命令和 position/velocity 状态接口。
物理接口源码已经存在，当前记录仍不足以认定完成新插件的 ROS 运行时或实机验收。

- [ROS 2 控制栈](ros2_ws/ROS2_CONTROL.md)
- [左臂硬件接入](ros2_ws/LEFT_ARM_HARDWARE.md)
- [验证记录：区分旧节点、新插件及实际执行环境](ros2_ws/VERIFICATION.md)
- [模拟性能基线及其适用范围](ros2_ws/SIMULATION_BASELINE_20260925.md)

旧 `arm_control` 是独立的低频 SDO/单点指令演示，不是新 `ros2_control` 插件的运行时验证替代品。
原有网页运行、打包和部署说明保留在 [WEB_PLATFORM.md](WEB_PLATFORM.md)。

## 工程目录职责

- `ros2_ws/src/linglong_control/`：标准轨迹控制、模拟/物理插件、诊断和控制核心。
- `ros2_ws/src/arm_control/`：旧 ROS 自定义节点与示意模型资源。
- `controller/`：IgH 单电机实验、设备观察、左臂维护脚本。
- `docs/ethercat/`：设备接入约定、专题代码索引、恢复设计和交付标准。
- `ethercat_bridge.py`、`ethercat_config.py`、`motor_profiles.py`：测试进程管理、平台配置与设备档案。
- `tests/`、`ros2_ws/src/*/test/`、`ros2_ws/verification/`：不同层级的测试与历史证据。
- `app.py`、`templates/`、`static/`：Web 测试界面；CAN/IMU、报告存储为配套功能。

工程只维护无编号的当前入口；无引用的 `_1/_2/_3` 历史副本已清理，历史版本可通过 Git 查询。
Web 启动使用 `app.py` 或 `run_gui.py`，依赖使用 `requirements.txt`；ROS 2 构建使用 `ros2_ws/src/`。
