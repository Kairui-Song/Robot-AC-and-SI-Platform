# 左臂 ROS2 系统约定 v1

适用：Ubuntu 24.04 / ROS2 Jazzy 的 `linglong_control` 四关节链。代码已有、离线检查、ROS 集成和实机验收是四种独立证据，统一记录在 `VERIFICATION.md`。
共享 Python 名称集中在 `linglong_control_tools/interfaces.py`；配置与测试保持对应。

## 节点、命名空间与所有权

本版采用**一个 ROS domain 一条左臂、根命名空间**。绝对话题/服务名为明确约定，单独增加节点 namespace 不会迁移整套控制链。尚不支持仅改一个 launch 参数就运行双臂；多臂扩展必须同时修改端点、控制器、URDF 关节名、TF frame 和录包配置。

- `controller_manager`：唯一控制器资源管理者与硬件 read/update/write 调度者。
- `robot_state_publisher`：唯一的模型 TF 发布者；使用 joint_state_broadcaster 的关节反馈。
- `linglong_control_diagnostics`：只读健康观察者，5 Hz 发布诊断，不下发运动和复位。
- `left_arm_motion`、`trajectory_demo`：有界 Action 客户端；前者四关节动作，后者 mock 验收。一次只运行一个动作客户端，低速度检查不等于排他任务锁。
- `linglong_fault_snapshot`：有界只读证据采集，服务异常保留部分证据。
- `left_arm_tf_probe`：只读 TF2 查询，最长等待 10 秒，不发布 TF。
- `linglong_archive_observer` 与 `linglong_bag_recorder`：记录流程中的发现观察者和录包进程。
- `linglong_replay_observer`：独立 domain 的回放观察者，回放不启动 controller_manager 或硬件插件。

旧 `arm_control` 是独立演示路径。不能与新栈同时发布同名关节状态，也不能与新 PDO 插件争用 EtherCAT。rosbag 录制不获得任何命令所有权。

## Topic / Service / Action

- `/joint_states`：`sensor_msgs/msg/JointState`，四关节 position/velocity，rad 与 rad/s。发布者为 joint_state_broadcaster，消费者为模型、录包和可视化。
- `/dynamic_joint_states`：`control_msgs/msg/DynamicJointState`，四关节状态、control_health；物理后端额外公开 EtherCAT 资源。消费者不能把物理标识等同于实机验收。
- `/arm_trajectory_controller/controller_state`：轨迹 reference/feedback，用于观测误差；不能证明 PDO 写入成功。
- `/diagnostics`：`diagnostic_msgs/msg/DiagnosticArray`，条目名 `linglong/control`，OK/WARN/ERROR/STALE 及原始健康字段。
- `/tf`、`/tf_static`：模型变换。根 `base_link`，当前末端 `link_5`。本模型全为活动关节，`/tf_static` 没有消息可以是正常情况。
- `/robot_description`：robot_state_publisher 提供描述，manager 接收；同次归档通过该节点实际参数保存展开后的模型。
- `/arm_trajectory_controller/follow_joint_trajectory`：标准 Action，必须包含 joint_1/2/3/5；记录 Goal UUID、接受响应、终态、终点反馈。取消请求不代表物理制动完成。
- `/controller_manager/list_controllers`、`list_hardware_components`：只读查询。`switch_controller`：显式改变控制器占用，架构实验使用 STRICT 及超时，不由诊断节点触发。

不另造一套与标准 Action 或 controller_manager 重叠的控制服务。bag 回放白名单中没有 `/joint_command`、轨迹命令 topic、服务事件或服务请求。

## QoS 约定

状态观察者使用 best-effort / volatile / 小队列，允许连接常见状态发布者；录包状态队列增大到 100。可靠性只说明传输策略，不等于消息无丢失或硬实时。
诊断使用 reliable / volatile；Action status 按标准 action status QoS 订阅，历史状态不能单独证明本次 Goal 成功。
`/tf_static` 和 Action status 的录包订阅为 reliable / transient_local，保留已有静态变换和状态历史；其他逐周期状态不依赖保留历史。
精确录包订阅配置在 `config/bag_qos.yaml`。`fault_snapshot` 保存实际发布端 QoS 和与其自身订阅端的兼容结果，不外推为所有端点均兼容。

回放验收使用可靠、volatile 的独立传输配置：先创建暂停的 player，等 recorder 对所有有数据的话题完成订阅，再调用 player Resume 服务。比较消息内容和每话题顺序，不验证原 DDS QoS 性能。

## 参数与配置

- launch：backend 默认 mock；hardware_config 只用于已确认的物理后端；rviz 控制显示；fault_after_cycles/dropout_after_cycles 只用于 mock。
- `controllers.yaml`：关节、接口、资源、100 Hz 默认更新目标和轨迹容差；物理配置可覆盖 update_rate。变更后重新启动，不把修改 YAML 文件等同于在线生效。
- 诊断节点：stale_timeout 默认 0.5 s、expected_backend、nominal_period 都为只读启动参数。改变行为应重启节点，不接受“参数值变化但内部逻辑未变化”。
- 硬件配置：身份、标定、限位、看门狗、DC、停机确认统一走 `left_arm_configuration.validate()`；未确认模板继续拒绝硬件启动。
- bag_profile.yaml：版本、话题类型/最低样本数、时间覆盖、最大间隙、跟踪误差及 TF 边；只接受固定状态白名单。v1 仅用于正常 mock 基线，故障注入录包预期会不通过正常验收。
- bag_session 的 root、scenario、duration、domain 是工具 CLI 选项，不冒充 ROS 动态参数。wave 才发送 mock 动作，observe 只观察。

归档保存安装目录中的配置、launch、Xacro、工具源码、package.xml、mock 插件 SHA256，以及 manager/controller/diagnostics/robot_state_publisher 的实际参数导出。源文件配置与实际参数均保留，便于识别差异。

## 时间基准

- 运动轨迹：`time_from_start` 为相对时间，接口单位秒/纳秒；从当前反馈生成，不复用旧 bag 的运动指令。
- 实时侧周期观测：steady_clock；应用服务/Action 等待、健康超时和 TF 等待窗口：monotonic/steady time。暂停 ROS `/clock` 不应让超时看门狗一起暂停。
- 消息 header/TF：ROS 时间；正常 mock 录包基线要求系统时间，use_sim_time=false。不把 steady 时间戳写入 ROS header。
- bag：本工具不用 `--use-sim-time`，记录接收时间；分析分别检查接收间隙和消息 header 单调性。录包频率/间隙不是 EtherCAT 周期或硬实时证据。
- 回放：保存原 header，接收时间重新产生；不发布 `/clock`，不启动实时健康监视器去判断历史 header 的新鲜度。回放比较忽略新接收时间及跨话题交错顺序。
- EtherCAT DC 应用时间纪元和稳定调用位置仍待专项复核，不由本次 ROS 时间规范推定已正确。

## Lifecycle、Executor 与 Callback Group

controller_manager 管理控制器装载、激活、停用和接口占用；SystemInterface 管理硬件配置、使能、读写、失能和错误。四关节作为整组申请/释放，错误后不自动恢复旧轨迹。
应用节点使用普通 Node；有限时长工具的生命周期是启动、采集/执行、超时或完成、释放资源退出。没有增加名义上的 LifecycleNode，也没有宣称存在系统级自动恢复管理器。

诊断订阅与定时器共享 MutuallyExclusiveCallbackGroup，由 SingleThreadedExecutor 串行执行；回调只处理内存和发布消息，不执行磁盘 I/O、服务等待或 shell。
TF probe 使用 TransformListener、显式 spin_once 和非阻塞 lookup；不得在同一单线程回调中阻塞等它自己接收 TF。
Action/Service 的有界等待位于工具主流程，通过 spin 推进完成；不是在订阅回调里同步等待同一 Executor 的其他回调。
录包、回放、参数导出与哈希/JSON 分析属于独立非实时工具；进程级等待有上限，退出优先 SIGINT 让 bag 完成 metadata，超时保留失败归档。
硬件启动握手允许在生命周期路径有界等待；周期 read/write 不调用 CLI/磁盘分析。现有插件的 mutex 和总线调用仍需后续实时性评估，不能宣称无阻塞或硬实时已验收。

当前没有引入 MultiThreadedExecutor。未来只有在真实并发需求下增加独立 callback group，并明确共享状态锁、取消和停机顺序，再用负载实验证明效果；增加线程数本身不算完成标准化。

## 验证分层与变更要求

1. 源码：接口、实现和安装入口可追溯。
2. 离线：纯逻辑、消息替身、假总线测试；不能证明 DDS、rosbag 插件或 ROS 生命周期运行。
3. ROS 集成：在 Ubuntu/Jazzy 运行实际 launch、动作、bag 录制和回放，保留 manifest、日志和判据报告。
4. 实机：独立保存 PDO、标定、停机与闭环记录；mock 和 bag 回放不能替代。

变更共享名称或关节顺序时，同步更新接口模块、controllers/Xacro、bag profile、测试和本文。新字段必须明确单位、来源、有效性和版本兼容性。完整操作流程见 `BAG_WORKFLOW.md`。
