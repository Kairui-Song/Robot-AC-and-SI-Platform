# 左臂接口、单位与故障编号

适用对象：当前 `linglong_control/LeftArmSystem`。本文记录现有接口，并明确待扩展字段；不改变设备配置。

## ROS 与设备对应关系

四关节顺序为 `joint_1 → p1`、`joint_2 → p2`、`joint_3 → p3`、`joint_5 → p5`。
这是部署位置映射，不表示所有机械臂都适用，也不包含 p4。

ROS 命令接口为 `position`，单位 rad；状态接口为 `position`/`velocity`，单位 rad/rad·s⁻¹。
状态向量和命令向量均按上述固定顺序导出，整组控制器切换不能只申请其中一个关节。
定义位置：[left_arm_core.hpp](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_core.hpp)、
[left_arm_system.cpp](../../ros2_ws/src/linglong_control/src/left_arm_system.cpp)。

## 对象字典与 PDO 约定

主站输出即驱动器接收：SM2 中要求 `0x607A:00`（32 位有符号目标位置）、`0x6040:00`（16 位控制字）。
主站输入即驱动器发送：SM3 中要求 `0x6064:00`（32 位有符号实际位置）、`0x606C:00`（32 位有符号实际速度）、
`0x6041:00`（16 位状态字）、`0x6061:00`（8 位有符号模式显示）。

初始化通过 SDO 写 `0x6060:00 = 8`。若 RxPDO 含可选 `0x6060:00`，周期输出也写 8。
适配器接受的其他输出为 `0x60FF`、`0x6071`、`0x60B0`、`0x60B1`、`0x60B2`，保持零；
这不表示开放速度、转矩或偏置命令接口。
方向、位宽、必要条目重复/缺失与未知输出均由配置检查处理。

以上是**代码要求**，不是现场 PDO 导出的替代品。实际布局核对入口为
[left_arm_bus.hpp](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp) 的 `verify_mapping()`。

## 标定与换算

位置：`joint_rad = (raw_position - zero_counts) / counts_per_radian`。
指令：`raw_target = round(zero_counts + joint_rad * counts_per_radian)`，并检查 int32 范围。
速度：`joint_rad_s = raw_velocity / velocity_counts_per_rad_s`。

两个比例可带方向，但必须各自来自设备单位与关节侧换算依据，不能凭相同字段宽度假定相同单位。
标定的零位、方向、减速比、限位和证据属于同一配置版本。
当前没有 ROS effort 接口；不把 `0x6077` 原始反馈直接标为 N·m。

## 已有健康接口

`control_health` 随 `/dynamic_joint_states` 发布八个字段：

- `mock`：模拟为 1，物理后端为 0；0 只是后端标记，不是实机验收结论。
- `active`：硬件控制核心是否激活，不是控制器资源占用状态。
- `fault_code`：插件本地故障编号；不等于驱动器 `0x603F` 错误码或 AL 状态码。
- `cycles`：该实现记录的控制周期计数，不是 EtherCAT 报文序号。
- `period_seconds`、`max_period_seconds`：观测周期及最大观测周期，单位 s。
- `deadline_misses`：超过 1.5 倍标称周期的观测次数。
- `feedback_age_seconds`：插件记录的反馈延迟信息，不代替原始 WKC 与采样时戳。

新插件发生故障时可导出 NaN 关节状态，避免把最后一次位置继续标作健康测量。
诊断与故障快照必须显式选择正确后端。

## 当前故障编号

- 1：非法/非有限数命令。
- 2：位置或编码器范围越界。
- 3：相邻目标步长超限。
- 4：跟随误差超限。
- 5：控制周期异常或超时。
- 6：反馈异常；左臂接收路径的不完整 WKC/在线状态检查失败也可能汇总为此码，不能据此单独认定物理原因。
- 7：模拟故障注入，物理左臂不使用此注入入口。
- 8：硬件生命周期错误。
- 9：左臂总线/设备配置或发送异常。
- 10：左臂驱动状态/模式异常。
- 11：左臂启动/使能等待超时。
- 12：左臂位置指令变化速度超限。

编号在 [health.py](../../ros2_ws/src/linglong_control/linglong_control_tools/health.py)、控制核心和插件间保持一致。
首错对应关节已知时同时锁存实际站号 p1/p2/p3/p5；总线级错误无逐站证据时为 -1，后续 lifecycle error 不覆盖它。

## 已实现的物理后端诊断扩展

`ethercat_bus`：`link_up`、`working_counter`、`wc_state`、`feedback_valid`、`dc_enabled`、`first_fault_slave`、`first_fault_cycle`、`last_good_cycle`、`state_valid`。
`ethercat_slave_1/2/3/5` 各有：`al_state`、`online`、`operational`、`status_word`、`mode_display`、`state_valid`、`sample_valid`。

`state_valid` 表示本次接收成功取得相应总线/从站状态；`sample_valid`/`feedback_valid` 还要求整组 WKC 完整、链路及四站均在线且 operational。无效字段可能保留旧值，不可解释为新鲜测量。有效性仅针对最后一次接收，还必须结合 ROS 接收时间、周期进度和 active 判断时效。
`dc_enabled` 只表示配置非零，不表示已测得同步效果。周期字段是本插件 read 计数，不是绝对时间；无首错时站号为 -1、周期为 0。配置阶段尚未进入 read 时也可能在周期 0 锁存故障。

diagnostics 附加原始字段，fault_snapshot 在 `ethercat_telemetry.resources` 保存这些报告值，JSON 非有限值转 null；原有 schema_version=1 及八字段健康接口保持兼容。其物理验证结论仍为 NOT_OBSERVED，不能把状态接口报告当作独立现场验证。
待补：设备 revision/serial、驱动错误码、绝对首错时戳、受控恢复阶段与重试次数，以及 ROS 运行时发布验证。
