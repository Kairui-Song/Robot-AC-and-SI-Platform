# ROS 2 + EtherCAT 工程主线

项目要能回答四个问题：**如何接入设备、如何按周期控制、如何定位故障、如何证明恢复可用**。
这些问题共同构成机器人控制系统工程能力，不能由协议关键词或单次动作截图代替。

## 推荐阅读顺序

1. [能力清单](CAPABILITIES.md)：把每个术语对应到具体文件与当前完成程度。
2. [分层架构](ARCHITECTURE.md)：沿着一条四关节命令理解调用和反馈关系。
3. [工程规范](ENGINEERING.md)：明确设备资料、标定、日志和证据应保存什么。
4. [诊断与恢复](RECOVERY.md)：区分掉站检测、阻断命令、通信恢复和重新允许运动。
5. [接口、单位与故障编号](INTERFACES.md)：核对现有 ROS/PDO 边界，区分本地故障码与设备原始错误。
6. [实施清单](ROADMAP.md)：按设备档案、逐站诊断、DC/周期、受控恢复推进后续工作。

## 代码阅读路线

从 [single_motor_preflight.c](../../controller/single_motor_preflight.c) 看设备扫描与身份信息；
从 [je_single_motor_test_v2.cpp](../../controller/je_single_motor_test_v2.cpp) 看 PDO 域和反馈；
从 [je_single_motor_csp_dc.cpp](../../controller/je_single_motor_csp_dc.cpp) 看 CSP、DC、绝对周期和阶段诊断。
这三者是单电机工具路线，不是整臂运行依赖。

整臂主线依次阅读：
[left_arm_hardware.yaml](../../ros2_ws/src/linglong_control/config/left_arm_hardware.yaml) →
[left_arm_configuration.py](../../ros2_ws/src/linglong_control/linglong_control_tools/left_arm_configuration.py) →
[left_arm_system.cpp](../../ros2_ws/src/linglong_control/src/left_arm_system.cpp) →
[left_arm_core.hpp](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_core.hpp) →
[left_arm_bus.hpp](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp)。

## 当前阶段

本轮是文档与工程入口规范化，没有执行集成或实机验证。
历史结论统一引用 [VERIFICATION.md](../../ros2_ws/VERIFICATION.md)，不把旧 arm_control 的 mock 联调、
新控制核心离线测试、ROS 运行时集成、实机闭环合并成一个“已验证”。

## 技术依据

- [IgH 1.6 应用 API](https://docs.etherlab.org/ethercat/1.6/doxygen/group__ApplicationInterface.html)：主站、从站配置、PDO/SDO、状态和 DC 的具体调用约定。
- [ETG 技术概览](https://www.ethercat.org/en/technology.html)：EtherCAT 通信与同步机制。
- [ROS 2 Jazzy SystemInterface](https://control.ros.org/jazzy/doc/api/classhardware__interface_1_1SystemInterface.html)：ROS 硬件生命周期和读写边界。

设备的 ESI、对象字典、DC 参数和制动要求以匹配型号/固件的厂家资料及现场导出为准。
