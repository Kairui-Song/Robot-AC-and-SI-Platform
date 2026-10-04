# 系统与硬件状态管理

适用入口为 `ros2 launch linglong_control control.launch.py`，目标 ROS 2 Jazzy。
旧 `arm_control` SDO 演示仍独立运行，不受本管理器控制。

## 默认行为与操作

启动只配置硬件和控制器。硬件保持 INACTIVE，轨迹控制器保持 inactive，
`joint_state_broadcaster` 发布反馈。系统确认新鲜反馈与组件状态后进入 READY。
启动不会自动执行四轴使能。

```bash
ros2 launch linglong_control control.launch.py backend:=mock rviz:=false
# 另一个终端，source 同一工作空间后：
ros2 topic echo /system/state
ros2 run linglong_control system_transition ready
ros2 run linglong_control system_transition enable
ros2 run linglong_control trajectory_demo  # 仅 MOCK
ros2 run linglong_control system_transition disable
ros2 run linglong_control system_transition shutdown
```

`system_transition` 等待目标状态并以非零退出报告失败；直接调用
`/system/enable`、`/system/disable`、`/system/recover`、`/system/shutdown`
（均为 `std_srvs/srv/Trigger`）只确认请求已接受，完成结果见 `/system/state`。
服务不能并发执行；SHUTDOWN 为终态，需要重启 launch。
请求响应包含转换序号；客户端忽略更早的缓存状态，避免把请求前的 FAULT 当成恢复失败。

## 系统层

`system_state.py` 是可独立测试的转换策略，`system_manager.py` 是非实时 ROS 适配器。

- UNINITIALIZED：等待组件和反馈；启动等待默认上限 45 秒。
- CONFIGURED：组件已配置或转换服务已完成，尚待一致的新鲜观测。
- READY：硬件 INACTIVE、轨迹控制器 inactive、广播器 active，反馈有效且周期持续推进。
- ENABLING：先激活硬件，再激活轨迹控制器，最后验证新鲜状态和整组命令所有权。
- ENABLED：已使能，无正在处理的轨迹 Goal。
- RUNNING：FollowJointTrajectory Goal 为 ACCEPTED、EXECUTING 或 CANCELING；不是循环线程正在运行的同义词。
- STOPPING：先停用轨迹控制器，再停用或关闭硬件。
- FAULT：故障锁存，拒绝使能；尝试停用控制器并将硬件退到 UNCONFIGURED。
- RECOVERING：显式恢复中；成功只能回到 READY，仍需再次显式使能。
- SHUTDOWN：硬件 lifecycle 已确认 finalized；不表示已测得机械停止。

正常路径：`UNINITIALIZED → CONFIGURED/READY → ENABLING → ENABLED ⇄ RUNNING`。
停止路径：`ENABLED/RUNNING → STOPPING → READY`；关闭路径经 STOPPING 到 SHUTDOWN。
启动阶段很短，CONFIGURED 不保证被每个订阅者观察到。

运行中的反馈中断、冻结的周期计数、故障码、组件状态与命令所有权不一致、
转换失败或超时均触发 FAULT。上层故障不会因下一帧恢复正常而自动解除。
状态包含转换序号、原因、后端、当前操作、最近操作结果、硬件阶段、
ROS lifecycle、控制器状态、反馈年龄与运动授权。
硬件阶段和故障码仅在反馈新鲜时作为当前值；广播器停用后，`feedback_fresh=false`，
当前硬件阶段为 UNKNOWN、当前故障码为 null。旧值位于 `last_observed_health`，
已观测到的故障原因位于 `last_observed_fault`，不能把历史 ACTIVE 当作实时使能证据。
偶发周期偏慢只保留诊断 WARN，故障阈值由硬件核心的 cycle_timeout 执行。

## MOCK 故障有序停用

新版 launch 在 MOCK 中显式启用 `supervised_fault_stop=true`。核心检测故障后立即锁存、
禁止运动和命令、令位置/速度反馈为 NaN，不再推进模拟周期；读写传输暂时返回 OK，
只为保留故障遥测与尚未释放的接口，不表示硬件健康。管理器先停轨迹控制器，再停广播器，
最后将硬件退到 UNCONFIGURED，避免框架先撤销接口后停止控制器的错误顺序。
系统故障仍锁存，拒绝 enable，必须显式 recover，且恢复只回 READY。
管理器退出会终止整个 launch；即使管理器暂时无响应，插件锁存也禁止模拟运动。
此策略仅用于模拟后端；独立加载插件默认关闭，物理 EtherCAT 后端仍使用原错误返回路径。

`/diagnostics` 用 `sample_age_seconds` 表示本地接收年龄；过期遥测键统一加
`last_observed.` 前缀。已观测故障记录独立保留，不把未知状态推断为零故障。
诊断还订阅 `/system/state`，广播器停止后仍可显示管理器锁存的首个故障原因。
该修复改善故障后的处理和展示，不消除宿主机/虚拟机长停顿，不放宽周期超时阈值。

正常应用通过管理器管理生命周期，通过原 FollowJointTrajectory Action 发送任务。
直接调用 controller_manager 改状态属于维护操作，可能被识别为外部状态改变并锁存故障。
直接发布控制器 `joint_trajectory` topic 不属于本系统的任务状态协议，
不能据此获得正确的 RUNNING 状态；需要该入口时应增加相应任务仲裁。
这不是针对任意 ROS 发布者的访问控制机制。

## 硬件层

两个插件共用 `hardware_state.hpp` 中的显式转换守卫：

`UNINITIALIZED → INIT → DISCOVERING → CONFIGURING → INACTIVE → ACTIVATING → ACTIVE`

ACTIVE 可以停用回 INACTIVE，INACTIVE 可以清理回 INIT。各非终态可进入 FAULT 或 SHUTDOWN；
FAULT 不能直接回 ACTIVE，恢复须经 RECOVERING → INIT，再重新配置。
实机 DISCOVERING 检查从站身份和 PDO 映射；CONFIGURING 注册 PDO、模式、看门狗和 DC 并建立初始反馈。
ACTIVATING 才执行原有 CiA402 使能过程。ACTIVE 表示整组硬件可用，不表示正在执行任务。
配置与正常停用还会在 startup_timeout 内确认四轴实际状态字均为 Switch On Disabled，
不会仅凭 controlword 0 已发送就报告 INACTIVE；超时锁存故障 11。

`control_health` 在原八项接口后增加：

- `hardware_state`：0 UNINITIALIZED，1 INIT，2 DISCOVERING，3 CONFIGURING，4 INACTIVE，
  5 ACTIVATING，6 ACTIVE，7 FAULT，8 RECOVERING，9 SHUTDOWN。
- `transition_sequence`：硬件状态变化次数。
- `commands_enabled`：整组控制器是否已取得命令接口。

ROS lifecycle 管理组件资源，自定义硬件阶段解释内部过程；
驱动状态字仍是实际使能依据。故障检测和命令阻断留在 C++ 控制路径，
不等待 Python 管理器、诊断主题或服务往返。

## 故障恢复边界

MOCK 支持 `/system/recover`：停用控制器、将硬件退到 UNCONFIGURED、显式重新配置、
恢复广播器并验证新鲜的未使能反馈。ROS on_error 可能已把组件置为 UNCONFIGURED；
因此 MOCK 的显式 on_configure 也可经 RECOVERING 清理核心故障。单独 activate 不能清故障。
系统故障锁存直到整个恢复流程通过验证。注入参数仍有效，重新使能后会再次注入，
取消持久注入需要修改参数并重启。模拟重新配置会重置到配置初始位置，不能当成实机恢复策略。

实机不实现自动驱动复位，`/system/recover` 返回拒绝理由。核心故障穿过 cleanup 仍保持锁存，
需排除现场原因后重启。系统故障停用操作不会自动重新配置或重新使能实机。
停用发送失败会锁存总线故障；软件请求成功不等于机械停止反馈已确认。

服务超时不等于远端服务取消。对于已发出的超时请求，管理器保持 FAULT、拒绝新操作，
默认每步 `operation_timeout=40` 秒，之后最多再等待 `late_reply_timeout=10` 秒。
迟到窗口内确认返回后再执行补偿停止，避免迟到的 enable 在 stop 之后重新使能。
超过窗口则结束本地操作，保持 FAULT，发布 `restart_required=true`、`operation=null`、
`last_result.success=false` 和 `last_result.completion_unknown=true`。
`intervention_reason` 给出人工处置步骤，所有新生命周期请求明确拒绝，不再报告模糊的“操作进行中”。
管理器移除本地 Future，但这不取消远端操作，也不证明驱动已停机；窗口后迟到回复不能解除锁存。
必须按现场独立停止流程保障机械臂、终止整个 controller_manager/launch、处理故障后再重启，
不能仅重启 system_manager。管理器仍持续发布状态并进行只读观测，不发送竞态补偿请求。
硬件周期保护、驱动看门狗和现场停止措施仍负责各自的底层故障响应。
管理器进程退出会触发整套 launch 关闭。

ListHardwareComponents/ListControllers 属于只读观测，超过 `stale_timeout`（默认 1 秒）
会移除并取消本地 Future、使对应观测时间失效，然后在服务可用时重新查询。
旧 Future 的迟到结果不参与状态更新；两个查询端点各自独立，不相互阻塞。

## 实机周期与生命周期互斥

实机 `read/write` 使用 `try_lock`：生命周期持有总线锁时立即返回，保留旧反馈，
不增加反馈周期计数，不提交控制器目标。生命周期循环独占 PDO 交换，发送对齐反馈的目标或失能字；
控制器取得命令接口时重新对齐命令，防止转换期间的旧指令随后被发送。
生命周期仅修改内部状态缓存；导出的反馈存储由周期线程刷新，避免控制器 update 与生命周期并发读写。
`perform_command_mode_switch` 在锁被占用时返回 ERROR，要求调用方等待转换完成后再请求。
正常无争用周期仍执行原有反馈、速度、限位与周期超时保护。
转换期间的缓存反馈不应被视为新测量，系统转换完成仍必须通过新鲜遥测验证。
该修改消除插件内周期读写等待生命周期锁的路径，不保证 controller_manager 调度、IgH 调用或操作系统延迟。
假总线并发测试覆盖持锁转换期间的读写返回、模式切换拒绝、反馈计数不伪造和激活后目标对齐。

## 验证

```bash
bash tools/verify_state_machine.sh
```

脚本使用独立 domain（默认 89），执行 Python 回归、ROS 插件构建与 CTest，
再启动 MOCK 验证初始未使能、ENABLED/RUNNING、任务完成、运行中停用、
故障后拒绝使能、显式恢复回 READY、SHUTDOWN 终态。
结果和状态历史写入 `verification/state-machine-时间/`。
假 IgH 总线测试还会编译和执行实机插件本体，检查四轴使能、停用发送失败及跨 cleanup 的故障锁存。
实机 PDO、驱动复位与负载停机仍须现场验证。
