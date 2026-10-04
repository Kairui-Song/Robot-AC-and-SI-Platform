# 验证记录

## 2026-09-29 系统约定、TF2 与 rosbag2 流程

本节与旧 arm_control 的用户 Ubuntu mock 记录、新 ros2_control 的离线检查分别计证。

- **源码实现**：共享接口名称；节点/命名空间、QoS、参数、时间基准和并发职责规范；有界 TF2 查询；正常 mock 录制配置、唯一运行目录、参数/源码/Goal UUID/结果/日志归档、SHA256 清单；SequentialReader 流式分析；独立 domain 的状态白名单回放、再次录制及逐话题内容摘要比对。
- **离线测试**：`linglong_control/test` 包内 125 项 Python 测试通过（上轮 96 项，本轮新增 29 项）；工具与 launch Python 编译语法检查通过。覆盖缺数据、坏时间戳、非有限值、错误后端、控制周期冻结、TF 异常、跟踪超限、错误 Goal UUID、回放缺帧/变更/重排、清单篡改、进程清理、录制就绪超时、player/recorder Resume 区分及录制执行器成功/失败归档。使用现有 WSL Python，不是 ROS 集成测试。本轮未改 C++ 核心，也未重复其测试。
- **ROS 集成**：未执行本轮 colcon 完整构建、真实 TF 查询、DDS discovery/QoS、rosbag2 sqlite3 录制/读取或回放验收。不存在本轮真实 bag 样本或 comparison.json 通过记录。用户后续按 BAG_WORKFLOW.md 执行，并将实际 archive 路径及结果补到本节。
- **实机证据**：没有连接主控或机械臂；没有新增 PDO、标定、制动、DC 或闭环证据。录包工具 v1 的正常验收 profile 仅接受 mock。

本轮未安装环境、未运行 ROS、未运行机械臂运动。未引入 MultiThreadedExecutor 或系统级自动恢复管理器；已明确目前的职责边界及后续引入条件。

## 可靠性、调度与恢复模拟基线（2026-09-25）

- 已实际编译运行新 `sim_validation` C++ 测试驱动，直接复用 `sim_core.hpp`，Release 构建。完整最终轮 10/10 场景通过。
- 864 万周期、24 小时等效虚拟控制时间，意外故障 0；不是 24 小时墙钟连续运行。
- 5400 次随机故障在轨迹运动过程中注入，全部正确检测并锁存；4200 次同实例复位、1200 次重建无故障模拟配置后恢复均通过；6000 次停用/激活检查通过。
- 空闲/双计算线程负载各三轮、每轮 20 秒，实际采集 12000 个周期；每轮计时均满足预设门槛，原始 CSV 的时间关系和分位数独立复算通过。
- 77 项 Python 回归通过，CTest 3/3 通过。源码和二进制 SHA256、编译器、主机及原始数据已保存。
- 指标、统计定义和范围见 [SIMULATION_BASELINE_20260925.md](SIMULATION_BASELINE_20260925.md)。没有新增任何 ROS/Jazzy 或真机已验证的声明。

## 分层故障证据采集（2026-09-25）

- 新增只读 `fault_snapshot`：收集 Action 历史、发布者/QoS、控制器状态与接口占用、硬件生命周期、目标/反馈窗口和健康转换时间线；保存不覆盖已有文件的 JSON。
- 不发送运动或复位请求；服务仅使用 ListControllers 和 ListHardwareComponents。服务共享超时窗口，测试验证单个服务不可用时仍保留另一个服务的证据。
- 63 项 Python 测试通过，其中原有 40 项、新增 23 项。新增覆盖缺失数据不误判总线故障、空闲不误判电机故障、过期/重放数据、历史 Action、非法帧、关节重排、有界缓存、报告覆盖保护及 Jazzy 消息字段契约。
- 18 个 Python 文件/脚本与 package.xml 语法检查通过；更新后的验收脚本通过 bash 语法检查。
- **未执行实际 ROS 图查询、DDS QoS 联调、控制器服务和现场证据采集。** 当前仍无 Jazzy 运行时；新增工具的 ROS 行为需要在用户的 Jazzy 环境验证。物理层明确标为未观测，未声称完成自动根因定位。

## 架构实验验收补充（2026-09-25）

- 新增轨迹取消匹配、取消后连续反馈保持、严格控制器切换及故障传播验收程序。模拟故障验收要求健康基线、指定故障码、异常诊断、控制器退出 active 和重新激活被拒绝共同成立。
- 离线 Python 回归共 40 项通过（新增包 26 项、原 arm_control 14 项）。新增判据覆盖错误 Goal UUID、取消拒绝、非有限反馈、位置跳变、非零速度、重复周期和观测时长不足。
- 13 个 Python 源文件/脚本和 package.xml 语法检查通过；更新后的验收脚本通过 `bash -n`。
- 本次没有修改 C++ 核心，前次记录的 16 个 C++ 场景结果继续适用。
- **仍未执行 ROS/Jazzy 运行时实验。** 离线测试证明判据逻辑，不证明真实 Action 取消、SwitchController 行为或故障传播已经通过。完整执行入口仍为 `bash tools/verify_ros2_control.sh`。

## ros2_control 模拟升级（2026-09-25）

本节仅记录本次直接执行的结果，不沿用旧包的 Ubuntu 联调结果作为新插件的证据。

- Windows Python 3.12.9：30 项 pytest 用例通过，其中新增包 16 项，旧 arm_control 回归 14 项。
- Python 检查包含诊断流中断、冻结周期计数、故障帧/NaN、非法健康数据、真实 xacro 展开、URDF 关节资源与 YAML 控制器/限位/周期配置一致性。
- WSL Ubuntu 26.04，GNU C++ 15.2.0，CMake 4.2.3：使用 `LINGLONG_CORE_ONLY=ON` 构建，开启 `-Wall -Wextra -Wpedantic -Werror`；CTest 1/1 通过，内部执行 16 个控制核心场景。
- C++ 场景覆盖非零反馈激活、有限速模拟、停用/再激活、完整多轴样本拒绝、NaN/Inf、关节限位、目标跳变、跟随误差、周期超时、反馈中断、锁存与显式复位、控制器停用保持和长轨迹。
- 9 个新增 Python 源文件/脚本 AST 解析成功，2 个包/插件 XML 清单解析成功；Ubuntu 验收脚本 `bash -n` 通过。
- 新增测试依赖位于项目 `ros2_ws/.test-deps`；C++ 产物位于 `ros2_ws/build-core`，均不属于交付源码，并加入忽略配置。经授权在 WSL 安装了 g++、CMake 和 make。

**未执行：** 当前 Windows/WSL 没有 ROS2/Jazzy；因此未编译链接 `linglong_sim_system` ROS 插件，未运行三个 ROS/gtest 插件测试，未执行 controller_manager 加载、launch、DDS、Action、RViz 或 rosbag 集成验证，也未连接任何 EtherCAT 硬件。

Jazzy 现场验证入口：`bash tools/verify_ros2_control.sh`。该脚本构建并测试包、运行 mock Action 和控制器重启验证，保存记录；故障注入与录包步骤见 `ROS2_CONTROL.md`。
当前可以确认控制核心/诊断逻辑及配置测试通过，不能据此宣称新 ros2_control 插件已完成 ROS 运行时联调或达到生产验收标准。

## 2026-09-28 四关节统一入口与逐站诊断（仅离线）

- 本轮 `linglong_control/test` 包内 Python 测试 96 项通过；范围为该包，不能与此前跨目录合计 112 项直接比较。
- C++ CTest 5/5 通过：left_arm_core、left_arm_bus、sim_core、validation_faults、validation_tracking；使用现有 WSL 工具和官方 IgH 1.6 头文件，假传输不访问主站。
- 新增动作规划测试覆盖四关节完整轨迹、当前位置起止、限位、速度、非有限值；消息替身测试覆盖单个四关节 Action、后端不符时拒发、目标拒绝及故障整组取消。
- 新增底层测试覆盖首错站号锁存、后续生命周期故障不覆盖首错、p5 离线、WKC 不完整及状态有效性；新增描述和快照字段检查。
- 新入口及后续命令见 [LEFT_ARM_MULTI_JOINT.md](LEFT_ARM_MULTI_JOINT.md)。没有安装环境、运行 ROS、连接主控或使机械臂运动。
- 完整 ROS 插件构建、真实 Action/lifecycle 交互、逐站诊断发布与真机闭环仍未验证；离线消息替身不等于 ROS 集成验证。

## 旧 arm_control 初始验证（2026-09-16）

- 环境：Windows；没有可用的 ros2、colcon 或 EtherCAT 硬件连接。
- 14 项 pytest 测试通过：标定往返、关节重排、非法输入、CLI 参数与实际读取、返回值解析、逐轴失能、模式检查、mock 数据隔离、回调反馈、部分写入失败、看门狗、轨迹拒绝、读取失败与过期指令。
- 回调测试使用 ROS 消息/节点替身，仅证明 Python 控制逻辑。
- 7 个 Python 文件通过 AST 语法检查；package.xml 与 URDF 通过 XML 解析；setup.py 的 6 组安装资源路径已核实。
- 上述本地测试未覆盖 ROS2 运行时；用户随后提供的 Ubuntu 模拟联调证据见下文。

## 用户提供的 Ubuntu 模拟联调结果

来源：本任务中用户粘贴的终端输出与 RViz 截图，非 Windows 端直接执行。

- 环境：VMware 开发虚拟机，Ubuntu 24.04，ROS2 Jazzy，Python 3.12.3。用户确认仅用于开发，未连接 EtherCAT 机械臂。
- `colcon build --symlink-install --packages-select arm_control` 成功，显示 `1 package finished`。
- launch 启动 arm_control、robot_state_publisher、rviz2 成功；日志明确为 `Backend=mock`。
- RViz 示意模型与 TF 已显示，截图中 `Global Status: Ok`。尚未取得目标变化前后的姿态对比截图。
- 初始 JointState 四关节位置均为 0；持续发送单点 JointTrajectory 后，joint_1/2/3/5 的模拟反馈分别为 `[0.03, -0.03, 0.02, 0.01]`，与目标一致。
- `ros2 topic hz /joint_states` 报告平均频率 4.997–5.004 Hz，最终窗口 82 条时为 5.001 Hz；记录的最小/最大间隔为 0.004/0.502 秒，最终标准差 0.04165 秒。平均频率符合 5 Hz 配置，但存在接收间隔波动，不能作为实时性保证，波动原因未定位。
- 停止指令后观察到 `Command watchdog expired`；重启后反馈恢复。此结果仅验证模拟模式超时处理，不证明硬件失能。

当前结论：已完成 ROS2 Jazzy 模拟指令与反馈通信、launch 启动、RViz 模型加载及平均反馈频率验证。

仍待验证：真实关节标定、EtherCAT 命令下发、编码器实际反馈、驱动使能状态、硬件异常与超时失能。后续追加主控现场记录；模拟位置不能作为实机闭环证据。

### 2026-09-25：诊断与验证报告完整性回归

- 控制器状态时间戳缺失、重复或回退时，保留采样指标，但标为 UNVERIFIED，抑制跟踪故障提示；异常采样离开保留窗口后可恢复正常判定。这也适用于仿真时钟暂停或复位，不将其归因为电机故障。
- 模拟验证运行器检查请求模式与输出场景一致性、汇总必需指标的数值类型及范围、九类故障记录完整性、调度原始 CSV 要求。格式错误转为失败用例并保留 stdout/stderr，避免汇总中断；合法的失败测量仍保留指标。
- Python 回归 87 项通过；WSL C++ CTest 3/3 通过。
- 短模拟 4/4 通过：1 小时虚拟时间、每类故障 5 次、空载及双负载各 2 秒。结果目录：`verification/simulation-20260925T083409-602579Z/`。本次用于验证工具兼容性，不替代此前性能基线，不新增 ROS2 集成或实机验证结论。
## 2026-09-26 左臂硬件后端离线验证

- 112 项 Python 测试通过（原有 87 项及 25 项左臂配置/描述/诊断测试）。
- 5 项 CTest 通过：left_arm_core、left_arm_bus、sim_core、validation_faults、validation_tracking。
- left_arm_bus 使用官方 IgH stable-1.6 的 ecrt.h 和假传输实现，不访问真实硬件。
- 完整 ROS 插件构建和 Action/lifecycle 真机联调未执行；当前 WSL 无 ROS Jazzy/IgH 库。
- 现场标定、PDO 映射、DC/看门狗与制动停机响应尚未核实，模板据此默认禁止硬件启动。
- 本轮只改源码和离线测试，没有运行主控部署或机械臂运动。

