# EtherCAT 底层程序索引

整臂 ROS 控制入口在 [linglong_control](../ros2_ws/src/linglong_control)，不是本目录某个单电机 main()。
专题说明见 [EtherCAT 工程主线](../docs/ethercat/README.md)。

## 设备观察与预检

- [single_motor_preflight.c](single_motor_preflight.c)：读取主控信息、从站数量、Vendor/Product、revision、serial 和 AL 状态；结果面向单电机预检，不能把“恰好一个从站”的成功条件用于整臂。
- [je_single_motor_test_v2.cpp](je_single_motor_test_v2.cpp)：JE 单从站 PDO 通信观察，输出位置/速度/原始转矩、WKC、链路与 AL 状态；循环保持 controlword 0，不是轨迹执行器。
- [install_je_single_motor_test_v2.sh](install_je_single_motor_test_v2.sh)：既有 JE 观察程序安装入口，其目标文件与网页配置对应。

## 单电机运动与诊断实验

- [je_single_motor_csp_dc.cpp](je_single_motor_csp_dc.cpp)：JE CSP/DC 阶段实验，包含绝对时间周期调度、模式探测、状态字判定和日志；CSV/CST 常量及模式探测不等于实现了对应闭环控制器。
- [je_single_motor_csp_internal_diag.cpp](je_single_motor_csp_internal_diag.cpp)：独立诊断实验变体。
- [je_single_motor_csp_internal_posdiag.cpp](je_single_motor_csp_internal_posdiag.cpp)：独立位置诊断实验变体。
- [ds402_probe.py](ds402_probe.py)：CiA402 诊断工具，使用前阅读其具体命令及写入行为。

这些程序不能因名称相似就替换默认可执行文件。JE 示例身份与左臂 EYOU 身份分开管理。

## 左臂维护与既有动作

- [ethercat_left_arm_test.py](ethercat_left_arm_test.py)：p1/p2/p3/p5 点动、反馈检查及退出处置，通过 CLI/SDO 通信。
- [dance_flow.sh](dance_flow.sh)：四关节固定波浪动作脚本，通过 CLI 下发，不是实时 PDO 轨迹控制器。
- [control_benchmark.py](control_benchmark.py)：会下发目标的测试脚本，测量包含其执行路径和 CLI 开销。
- [install_left_arm_service.sh](install_left_arm_service.sh)：既有左臂脚本部署入口。

## 新左臂控制代码

- [left_arm_core.hpp](../ros2_ws/src/linglong_control/include/linglong_control/left_arm_core.hpp)：整组目标、标定、状态校验和故障锁存。
- [left_arm_bus.hpp](../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp)：IgH 主站、身份/PDO 检查、过程映像、WKC 与 DC 配置。
- [left_arm_system.cpp](../ros2_ws/src/linglong_control/src/left_arm_system.cpp)：ROS 硬件生命周期、接口所有权与 read/write 适配。

归档原则：先核对调用者、部署文件和用户现场用途，再合并或迁移实验变体；不直接删除同名副本或修改默认运动入口。
