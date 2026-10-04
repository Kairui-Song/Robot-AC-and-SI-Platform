# 能力清单与完成边界

状态规则：**代码已有**仅指源码可追溯；**离线验证**、**ROS 运行时验证**、**实机验证**必须分别有执行记录。
本文依据源码维护；本轮新增记录仅涉及离线检查，不新增 ROS 或实机验证结论。

## Master / Slave、设备身份、AL State

[预检程序](../../controller/single_motor_preflight.c) 使用 `ecrt_request_master`、`ecrt_master_get_slave` 读取从站身份及 AL 状态。
[左臂总线适配](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp) 固定对接 p1/p2/p3/p5，检查 EYOU Vendor/Product。
现有单电机预检的通过条件不适用于四关节总线。

应能解释：总线位置不是电机型号；AL 的 OP 不代表 CiA402 已 Operation Enabled。
逐站 AL/online/operational 已加入物理插件状态接口；待补 revision/serial、拓扑档案及运行时发布验证。

## ESI 与 CoE

[motor_profiles.py](../../motor_profiles.py) 已明确保留未知设备身份和 PDO 信息。
代码通过 CoE 对象字典使用 PDO/SDO，但仓库目前没有确认过的左臂 ESI 和现场 PDO 导出档案。

应能解释：ESI 是设备描述资料，SII/在线对象字典是不同的信息来源；代码包含对象索引不意味着已经核对 ESI。
待补：厂家、固件适用范围、ESI 文件哈希、现场导出和差异说明，模板见 [设备记录](commissioning.template.yaml)。

## PDO / SDO

[左臂总线适配](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_bus.hpp) 注册过程数据、校验方向/位宽、整组发送；
SDO 用于配置 CSP 模式。旧 [左臂测试脚本](../../controller/ethercat_left_arm_test.py) 用 CLI/SDO 读写位置。
应能解释：低频 SDO 调通证明对象访问成立，不证明周期 PDO 控制性能。

## WKC 与链路诊断

JE 程序保存原始 `working_counter`/`wc_state`；左臂插件检查 `EC_WC_COMPLETE`、link、online、operational，异常时锁存整组故障。
WKC 用于判断报文操作完成情况，不等于“在线从站数量”；最终期望值取决于配置和报文处理。
左臂已导出原始 WKC、逐站状态及首错站号/周期，并接入诊断和快照；未知故障站为 -1。离线 fake transport 覆盖 p5 掉站与 WKC 不完整；实际 ROS 发布和物理故障行为仍待验证。

## Distributed Clocks / Sync0

[JE DC 实验](../../controller/je_single_motor_csp_dc.cpp) 有 AssignActivate、Sync0 cycle/shift、应用时间与时钟同步调用。
左臂插件有 DC 配置入口，模板默认 `dc_assign_activate: 0`；存在调用不代表已启用或测得同步效果。

待补：现场 DC 参数来源、Sync0 相位/周期记录、同步偏差测量；复核左臂插件应用时间的时基与调用位置。
IgH 官方要求应用时间按规定纪元表示并在周期中保持稳定调用位置；当前适配器使用 steady_clock 的实现需要专项评审，不能直接作为 DC 正确性证据。
依据：[IgH application_time API](https://docs.etherlab.org/ethercat/1.6/doxygen/group__ApplicationInterface.html)。

## CiA402、CSP / CSV / CST

[左臂控制核心](../../ros2_ws/src/linglong_control/include/linglong_control/left_arm_core.hpp) 校验状态字、模式显示和使能条件；当前 ROS 左臂命令接口仅支持位置/CSP。
JE DC 实验包含 CSV/CST 模式探测，但没有据此认定完成速度或转矩闭环。
应能解释：写入 `0x6060` 与读回 `0x6061` 是两件事；模式确认还要与状态字、有效反馈结合。
待补：若增加 CSV/CST，分别设计单位、限幅、状态切换和验收，不复用位置接口冒充支持。

## cyclic task 与 jitter

JE 实验有 `CLOCK_MONOTONIC`、`TIMER_ABSTIME`、deadline/lateness/missed_cycles 日志；左臂插件由 controller_manager 的同步 read/update/write 调度。
这两条路径的周期、运行环境及指标不能混用。
已有 [模拟基线](../../ros2_ws/SIMULATION_BASELINE_20260925.md) 是控制核心和 WSL 调度测量，不是机械臂总线同步性能。
待补：统一定义实际周期、唤醒延迟、执行时长和丢周期；保留原始样本、负载条件及预先确定的门槛。

## 位置 / 速度 / 转矩反馈

JE/旧左臂工具读取位置、速度和原始转矩值；新左臂 ROS 插件导出 position/velocity，**未导出 effort**。
原始 `0x6077` 数值不能未经设备额定转矩和单位换算就标成 N·m。
待补：设备反馈单位、方向、减速比和零位档案；需要 effort 时另补可靠换算与接口。

## slave recovery

左臂插件已有掉线检测、命令阻断、整组失能尝试和故障锁存；并没有完成自动掉站重配置、重新使能和恢复轨迹。
cleanup/restart 是当前软件恢复入口，不等于设备恢复已通过现场验证。
下一步设计见 [RECOVERY.md](RECOVERY.md)；旧点动脚本“回原位”不是总线掉站恢复。

## 对外介绍项目的依据

当前可描述：基于 IgH 开发执行器接入与 CSP 周期通信/诊断代码，构建 ros2_control 四关节插件与整组控制边界，完成已有记录中的离线验证。
“实现自动掉站恢复”“CSV/CST 已闭环”“新栈实机联调完成”“达到某实时性指标”须待对应证据形成后再增加。
