# Linglong ros2_control 模拟控制栈

当前启动先进入 READY，显式调用 `ros2 run linglong_control system_client enable` 后再执行动作；网页入口和完整步骤见 [WEB_CONTROL.md](WEB_CONTROL.md)。

统一约定见 [SYSTEM_CONTRACT.md](SYSTEM_CONTRACT.md)，自动录制/归档/分析/回放验收见 [BAG_WORKFLOW.md](BAG_WORKFLOW.md)。后者已替代仅有手动录包命令的操作入口，但尚无本轮 ROS 实际运行记录。

本次按“先模拟闭环与接口，再按现场配置接硬件”实现。目标环境为 **Ubuntu 24.04 + ROS2 Jazzy**。

性能与可靠性模拟验证见 [SIMULATION_VALIDATION.md](SIMULATION_VALIDATION.md)：包含 24 小时等效仿真、随机故障/恢复、空闲及 CPU 负载下的真实计时，并保存原始结果。
新增 `linglong_control` C++/ament_cmake 包，复用 `arm_control` 的示意 URDF/RViz 资源。
旧 `arm_control` 的 Python 单点 SDO 节点保留为独立演示，新的 launch 不会启动它。

默认仍是具备工程约束的**模拟集成版本**。新增可选四关节左臂 IgH PDO 后端
`backend:=ethercat_left_arm`，复用原有左臂 p1/p2/p3/p5 的协议约定，接入说明见
[LEFT_ARM_HARDWARE.md](LEFT_ARM_HARDWARE.md)。该后端已做离线核心/假总线验证，尚待 Jazzy 完整构建与真机联调，未完成生产验收。
旧拼写 `backend:=ethercat` 仍拒绝启动；物理后端不退回模拟或调用 SDO CLI。

## 已实现的控制链

`FollowJointTrajectory Action → joint_trajectory_controller → position command interface → SimSystem → 模拟位置/速度反馈 → joint_state_broadcaster → TF/RViz`

- C++ `hardware_interface::SystemInterface` 插件，通过 pluginlib 加载。
- 四关节 `joint_1/2/3/5`，position 命令，position/velocity 状态。
- controller_manager 的同步 `read/update/write`，目标 100 Hz。没有另建总线线程，没有在周期内使用 shell、网络、休眠或日志。
- 模拟器按最大 0.1 rad/s 接近目标，区别于原先收到目标就瞬间赋值的 mock；这不是动力学模型。
- 标准多点带时间轨迹、Action 状态/取消及路径与终点容差由 joint_trajectory_controller 负责。
- 支持整组关节的控制器资源切换；停用后保持模拟反馈位置，重新激活时丢弃旧目标。
- 激活从非零反馈 `[0.15, -0.10, 0.05, 0.02]` 初始化命令，避免默认零目标。
- 写入前校验完整指令：有限数、关节范围、相邻目标变化、跟随误差；全部通过后才提交整组目标。
- 周期超时、模拟反馈超时和注入故障锁存，向 controller_manager 返回 ERROR；不自动恢复。
- `/dynamic_joint_states` 附带 `control_health` 的 mock 标识、激活状态、故障码、周期数、间隔、最大间隔、超期计数和反馈年龄。
- 独立 Python 诊断节点用单线程 Executor 和互斥 Callback Group 串行处理状态，使用 steady timer/monotonic 时间检测数据中断及冻结的周期计数；不参与控制线程。
- 订阅采用 best-effort、volatile、小队列；诊断发布 5 Hz。静态诊断参数只读，避免运行中参数值改变而实际逻辑未更新。

硬件插件使用 Jazzy 保留的 `on_init(HardwareInfo)` 和显式导出接口 API，便于与较早 Jazzy 安装兼容；新版本可能产生 deprecation 警告。未宣称支持其他发行版。异步硬件模式被显式拒绝。

## 安装、构建和模拟运行

在 Ubuntu/Jazzy 环境执行，路径替换为你的项目路径。首次使用 rosdep 时按 ROS 官方说明完成初始化。

```bash
source /opt/ros/jazzy/setup.bash
cd /path/to/linglong_1025_2/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
ros2 launch linglong_control control.launch.py
```

没有桌面时加 `rviz:=false`。运行前关闭旧 `arm_control.launch.py`，避免 `/joint_states` 多个发布者。
新的启动文件按 broadcaster 成功 → trajectory controller 的顺序启动，spawner 失败或 manager 退出会关闭整套 launch。

另一终端 source 相同环境后：

```bash
ros2 control list_controllers
ros2 control list_hardware_components
ros2 control list_hardware_interfaces
ros2 run linglong_control system_client ready
ros2 run linglong_control system_client enable
ros2 run linglong_control trajectory_demo
```

`trajectory_demo` 只接受新鲜、健康、明确标记为 MOCK 的反馈。
它从当前模拟反馈生成 2 秒小幅位移、4 秒返回起点的两点轨迹，检查 Action 结果和新鲜终点反馈。
成功输出 `MOCK Action and final feedback verified`。它不会向旧 `/joint_command` 发送指令。
ROS 服务发现、反馈等待和 Action 完成都有时间上限；已接受但未结束的目标在异常退出时尝试取消。

`100 Hz` 是配置目标。实际周期测量来自 `steady_clock`，诊断中的 `deadline_misses` 表示观测间隔超过 15 ms 的次数，不等于精确丢帧数；`max_period_seconds` 是本次配置以来的最大间隔。
若单次活动控制间隔超过 0.5 秒，模拟器锁存故障。停摆期间软件本身无法执行任何保护动作，只有恢复执行后才能检测。

## 测试、故障注入和录包

完整 ROS 验收入口：

```bash
bash tools/verify_ros2_control.sh
```

它构建两个包，运行单测，在独立 ROS domain 87 启动 mock，验证轨迹、取消、控制器停用/再激活，以及反馈中断和注入故障，保存日志到 `ros2_ws/verification/` 的独立运行目录。故障实验各自重新启动模拟栈，不沿用上一轮日志。
需要自定义 domain 时设置 `LINGLONG_TEST_DOMAIN_ID`。确保该 domain 没有其他节点。
脚本不执行 rosdep，不连接硬件，不使用 sudo。测试失败时返回非零状态。

### 四组架构实验与判据

1. **轨迹执行：应用目标与周期命令的区别。** `trajectory_demo` 发送一次 4 秒轨迹，要求 Action 成功且新的终点反馈在 0.005 rad 内。观察 `trajectory.log` 中的初始位置和终点误差，结合 `controllers.yaml` 中的更新周期解释为什么不需要持续重发目标。
2. **轨迹取消：请求成功与实际停止的区别。** `trajectory_demo --cancel` 确认运动已经发生，再取消该 Goal UUID，要求收到对应取消确认和 CANCELED 终态。模拟器允许 0.3 秒稳定时间，随后至少连续观测 0.6 秒、10 个新周期样本；位置偏差不得超过 0.002 rad，反馈速度不得超过 0.02 rad/s。证据在 `cancel.log`。这不是机械臂安全制动验证。
3. **控制器重启：资源所有权与硬件状态的区别。** `architecture_probe restart` 使用严格 SwitchController 服务，核实 active → inactive → active，并在两次切换前后检查位置保持。服务等待期间收到的反馈也参与校验，避免只比较切换结束后的两个点。证据在 `restart.log`；然后再次执行正常轨迹，证明恢复控制能力。
4. **故障传播：底层异常与上层可用性的关系。** 每次从健康 MOCK 和 active 控制器开始，分别注入反馈中断（6）和模拟故障（7）。要求本轮插件日志有准确故障码、诊断 ERROR/STALE、控制器不再 active，并且严格重新激活请求被拒绝。缺少初始反馈、没有启动广播器、单纯服务超时，都不能作为通过证据。查看 `dropout.log`、`fault.log` 及对应 launch 日志。

成功的实验输出一行 JSON 判据结果，日志中的 `passed: true` 只代表该实验。整个脚本最后打印全部通过，才代表这一轮完整验收完成。观察到的反馈只是采样证据，不能排除两个样本之间的瞬态。

已经手动启动正常 mock 时，可单独运行前三组：

```bash
ros2 run linglong_control trajectory_demo
ros2 run linglong_control trajectory_demo --cancel
ros2 run linglong_control architecture_probe restart
```

对应阅读顺序：`trajectory_demo.py`（任务请求/取消与反馈证据）→ `architecture_probe.py`（控制器服务和故障传播）→ `sim_system.cpp`（接口所有权和生命周期）→ `sim_core.hpp`（模拟执行及保护）→ `health.py`（非实时健康判断）。

执行后，应能解释：取消 Action 为什么不等于停用硬件，控制器 inactive 时为什么仍有反馈，硬件报错后为什么诊断可能变成 STALE，以及为何不能用“成功发送命令”证明电机完成动作。

分别重启 launch 做故障验证：

```bash
# 约 5 秒后触发模拟故障
ros2 launch linglong_control control.launch.py rviz:=false fault_after_cycles:=500

# 约 5 秒后停止产生新反馈，再超过 0.1 秒触发反馈超时
ros2 launch linglong_control control.launch.py rviz:=false dropout_after_cycles:=500

# 另一终端观察
ros2 topic echo /diagnostics
ros2 control list_controllers
ros2 control list_hardware_components
```

预期故障后不能继续执行轨迹。controller_manager 可能停用包括 broadcaster 在内的依赖控制器，导致故障码来不及经话题发出；此时独立诊断应转为 STALE，而不能继续显示健康。插件错误回调记录故障码。
故障码：1 非法数值/形状，2 位置越限，3 目标跳变，4 跟随误差，5 周期超时，6 反馈超时，7 注入故障，8 生命周期错误。
故障后的简单恢复方式为停止 launch、取消注入参数后重新启动；单纯再次 activate 不清除故障。
核心支持显式 cleanup → configure 后复位，实际 ROS 错误状态能否通过 CLI 到达该路径取决于框架状态，因此默认验收使用完整重启。

录包用于复现接口和反馈，不能证明硬实时性能：

```bash
ros2 bag record -o mock_control_run \
  /joint_states /dynamic_joint_states /diagnostics /tf /tf_static \
  /arm_trajectory_controller/controller_state \
  /arm_trajectory_controller/follow_joint_trajectory/_action/status \
  /arm_trajectory_controller/follow_joint_trajectory/_action/feedback
```

上述 bag 不包含 Action 的 send_goal 服务请求。复现目标应同时保留 `trajectory_demo` 版本、配置和运行日志；若要记录任意 Action 请求，应使用目标 ROS/rosbag2 版本支持的服务事件记录方式。

## 分层故障证据：机器人为什么不动

在已 source 的 Jazzy 环境、与控制栈相同 ROS domain 中运行只读快照：

```bash
ros2 run linglong_control fault_snapshot \
  --duration 3 --output verification/incident-001.json
```

该工具不会发送轨迹、切换控制器、复位驱动器或执行 EtherCAT 命令；只订阅状态、查看发布者/QoS，以及调用 `list_controllers`、`list_hardware_components` 两个只读服务。观察时长 0.5–60 秒，之后两个服务共享最多 3 秒的收集窗口；部分服务不可用时保留其他证据并记录错误。

复现异常时可使用 `--duration 30 --until-fault`：必须先观察到健康反馈，再出现 ERROR/STALE，才提前结束。启动时没有数据不会被当作复现成功。`collection_completion` 说明是窗口到期还是观察到健康→异常；这个标志不等于故障根因已经确认。

报告分别记录以下内容：

- **应用请求：**最多 32 个 Action Goal UUID、状态和目标时间戳。Action status 是可能被保留的历史，不能证明你这次提交的目标已被接受；被拒绝的目标也可能不在状态列表中。需要与客户端接受响应、结果及错误文本关联。
- **ROS 通信：**发布者名称、消息类型、可靠性和持久性，以及与本快照订阅者的 QoS 兼容结果。这里不验证“应用发指令→控制器收指令”那一对端点；无发布者可能是发现/域配置问题，不直接等于进程不存在。
- **控制器：**实际生命周期状态、类型、claimed interfaces。active 与取得全部预期关节接口分别记录；inactive 可能是主动停用，也可能是硬件故障的后果。
- **目标与反馈：**最多保留 512 个有效 controller_state 样本，记录覆盖时长、目标/反馈变化范围、跟随误差、最后数据年龄和 ROS 时间戳。字段不是整个运行期间的统计；长时间收集时仅覆盖最近保留窗口。
- **硬件接口：**组件生命周期、命令接口是否可用/被占用，以及 dynamic_joint_states 中的健康状态和关节反馈。控制器 reference 不能证明 HardwareInterface 已成功 write，更不能证明 PDO 已发出，因此 `hardware_command_write` 明确标为 NOT_OBSERVED。
- **物理层：**EtherCAT 周期/AL、CiA402/使能、编码器均为 NOT_OBSERVED。当前没有经过验证的物理遥测适配器，不能把 mock 的数据填入这些层。

`findings` 中每项包含观察事实、下一步检查，`root_cause_confirmed` 始终为 false，顶层 `root_cause` 为 null。它是收集和整理证据的工具，不是自动认定根因的专家系统。目标不变可能是空闲或保持；目标变化而反馈不变仅提示进一步检查。故障码可以确认插件报告了哪个触发条件，但不能单凭反馈超时认定“网线断了”。

状态转换时间线最多保留 64 条，并报告丢弃数量。报告拒绝覆盖已有文件，严格使用 JSON，故障帧中的非有限位置记录为 null。多数据源按各自时间采集，并非原子快照；诊断节点是非实时观察者，采样间的瞬态仍可能遗漏。

完整验收脚本现在自动保存 `normal-evidence.json`、`dropout-evidence.json`、`fault-evidence.json`。故障快照与故障实验并行采集，快照本身不改变控制状态。脚本的通过/失败仍由独立验收判据决定；成功写出 JSON 只代表完成采集，不代表机器人健康或根因已定位。

整理真实排障案例时，把本次 JSON、对应 launch 日志和客户端 Goal UUID 保留在一起，再补充：触发操作、候选原因、逐步排除的证据、实际修复、修复后的同条件回归。没有证据的原因保留为待验证，不写成已定位。

代码入口：`fault_snapshot.py` 负责 ROS 只读采集，`evidence.py` 负责有界缓存、证据分类和报告保存。离线测试使用消息形状替身，不代替 Jazzy/DDS 的运行时验证。

## 当前校验边界

这是位置命令接口的模拟工程框架。新增 `left_arm_motion_plan` 对它自身生成的轨迹检查位置和线性插值速度；物理左臂核心还有命令速度保护，但没有全局加速度/jerk 或碰撞准入检查。`max_command_step` 是相邻目标跳变保护；模拟器的 `max_velocity` 不能被当作真机驱动器限速。
Action 取消沿用轨迹控制器行为，不等同于机械系统制动或安全停机。停止发布新轨迹不触发“命令超时”：一条有限时长 Action 轨迹无需持续重发 topic。周期停止和反馈中断单独监测。

无 ROS 的 C++ 核心测试：

```bash
cmake -S src/linglong_control -B build-core -DLINGLONG_CORE_ONLY=ON
cmake --build build-core
ctest --test-dir build-core --output-on-failure
```

Python 诊断、URDF/控制器一致性测试（需要 pytest、PyYAML、xacro）：

```bash
PYTHONPATH=src/linglong_control:src/arm_control \
  python3 -m pytest src/linglong_control/test src/arm_control/test -q
```

## 后续真机接入边界

已新增独立 `linglong_control/LeftArmSystem` 插件，物理描述生成器替换插件名；继续复用上层 Action、关节接口、控制器配置和可视化。该实现尚待完整 ROS 构建与现场验收，不需要再新增一个重复的 `EthercatSystem`。
不要把 `SimSystem` 改名后直接作为真机驱动，也不要在 read/write 中包一层 `ethercat upload/download`。

接入前需要现场确认：

1. 主站实现及版本、各轴从站位置、vendor/product/revision 和实际 PDO/ESI 配置。
2. counts/rad、正负方向、零位、机械限位和反馈速度对象的实际单位。
3. 总线周期、DC 配置、PDO watchdog、工作计数和从站状态检查方式。
4. CiA402/CSP 使能顺序、初始目标对齐、制动器配合、故障响应和明确的人工恢复条件。
5. 总线唯一写入者：选择 controller_manager 同步驱动 PDO，或与已有周期线程交换带时间戳/序号的完整快照。不可两套线程/进程同时写同一主站。

已有 JE C++ 文件包含单电机特定 PDO 映射和固定测试轨迹，四关节 Python 程序使用另一条 SDO 路径；这两份程序不能直接拼成通用多轴驱动。
模拟限位与跟随误差策略需要根据真机的制动、重力负载和驱动器能力重新验证；诊断和普通 ROS 停用不替代 STO/硬件急停。

参考：[硬件组件接口](https://control.ros.org/jazzy/doc/ros2_control/hardware_interface/doc/writing_new_hardware_component.html)、[控制器管理](https://control.ros.org/jazzy/doc/ros2_control/controller_manager/doc/userdoc.html)、[关节轨迹控制器](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html)。
