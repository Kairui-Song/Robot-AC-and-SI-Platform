# 分层架构与接口约定

## 应用层：提交任务

应用通过 `/arm_trajectory_controller/follow_joint_trajectory` 提交带时间的四关节轨迹。
关节名称固定为 `joint_1/2/3/5`，位置单位 rad。控制器拒绝缺少关节的部分目标。
Web/SSH 和旧 CLI 脚本是维护通道，不加入实时 read/update/write 调用链。

## ROS 控制层：轨迹与资源所有权

[controllers.yaml](../../ros2_ws/src/linglong_control/config/controllers.yaml) 定义轨迹控制器及状态广播器。
controller_manager 调用硬件 read、控制器 update 和硬件 write；控制器提供当前时刻的位置指令。
Action 负责目标执行与取消反馈；SystemInterface 负责生命周期、硬件接口导出与整组接口切换。

现有 [SimSystem](../../ros2_ws/src/linglong_control/src/sim_system.cpp) 与
[LeftArmSystem](../../ros2_ws/src/linglong_control/src/left_arm_system.cpp) 是可选后端，不能同时控制同一组执行器。
原 `arm_control` 自定义节点使用不同控制路径，不由此控制器管理。

## 控制边界：整组校验

[LeftArmCore](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_core.hpp) 承担标定换算、有限数/限位/步长/速度/跟随误差校验、状态字及模式检查。
所有关节校验通过后才提交一组目标。任何一个关节失败都会锁存故障，避免只更新部分关节。
启动目标来自反馈，控制器重新取得接口时丢弃旧目标。

配置、生命周期、控制器状态与 CiA402 状态必须分开解释：
配置成功不意味着使能；控制器 active 不足以证明总线反馈健康；AL OP 也不是 Operation Enabled。

## 总线层：过程数据交换

[LeftArmBus](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp) 申请 IgH 主站，为四个从站配置同一 PDO domain，检查设备身份、对象位宽和映射。
周期交换包含 receive/process、状态检查、过程映像读写和 queue/send；配置 SDO 在非周期初始化阶段处理。
驱动器目标和反馈使用原始整数单位，与 ROS 的 rad/rad·s⁻¹ 之间由各关节标定参数换算。

同一次 send 提交整组过程映像，不等于已经证明各驱动在同一硬件时刻采样/执行；后者还需要 DC/Sync0 配置及测量。
目前接口没有 effort，也没有逐从站原始诊断话题，不把其他单电机程序的反馈字段算到此插件上。

## 周期与时间约定

- 左臂周期由 controller_manager 驱动，默认配置 100 Hz；JE 独立实验自己的 1 ms 循环不是左臂运行频率。
- 控制时间间隔和超时使用单调时钟；日志可附墙钟时间用于关联，但不能用可回拨墙钟计算超时。
- DC 应用时间须遵循 IgH 的 API 时基、调用位置和同步关系；现有实现的评审项见 [能力清单](CAPABILITIES.md)。
- 唤醒延迟 = 实际唤醒时间 − 计划截止时间；周期偏差 = 相邻周期起点间隔 − 标称周期；执行时长 = 本周期结束 − 本周期开始。三者分别统计。
- `deadline_misses` 在模拟插件中是超出 1.5 倍标称周期的观测次数，不是精确丢帧或 DC 同步误差。

## 故障路径与停机语义

总线/驱动异常 → 控制核心故障锁存 → 阻断后续目标 → 尝试整组失能 → ROS 返回 ERROR → 上层控制器/诊断反映异常。
诊断订阅器只负责观察与报告，不能成为周期路径里的唯一故障保护。

轨迹取消、控制器停用、硬件停用及物理急停是不同操作。现有左臂策略是：
控制器接口切换时保持当前反馈；硬件停用/故障时尝试发送 controlword 0。
该策略对重力负载及制动器的适用性尚待现场确认，不能用“发送成功”代替“完成停机”。

## 运行所有权

新左臂插件使用 IgH 主站 reservation；它不阻止所有 CLI/外部维护命令。
现有 Web 进程互斥不能自然扩展为跨 ROS、脚本、主机的统一租约。
后续要做统一运行入口及所有权管理，不能宣称当前已经实现全链路互斥。

完整启动与运行范围见 [LEFT_ARM_HARDWARE.md](../../ros2_ws/LEFT_ARM_HARDWARE.md)。
