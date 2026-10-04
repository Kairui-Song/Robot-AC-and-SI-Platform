---
name: linglong-control-reliability
description: 修复并验证 Linglong ROS 2 Jazzy 控制栈的故障停用、诊断新鲜度、生命周期恢复及 Windows/Ubuntu 交付版本一致性。用户明确要求维护该控制栈或制作虚拟机交付包时使用。
disable-model-invocation: true
---

# Linglong 控制栈可靠性维护

工作目录为项目根目录，源码位于 `ros2_ws/src`；主要控制包为 `linglong_control`。

1. 阅读 `ros2_ws/STATE_MACHINE.md`、相关实现与现有测试。主环境为 Ubuntu 24.04 / ROS 2 Jazzy。
2. 区分只读查询与改变硬件状态的请求。只读请求可超时清理并重试；迟到结果不得刷新旧观测。
3. 生命周期 Future 超时或本地取消不代表远端操作取消。保留有限迟到窗口；未知完成结果必须锁存、阻止冲突操作，并给出完整控制栈重启步骤。
4. 周期读写不得等待生命周期中的睡眠循环。保持总线单一所有权，不以缓存反馈推进健康周期，不在激活后重放旧目标。不要仅为降低延迟删除互斥或故障保护。
5. 修改 Python 管理器时补充 ROS 替身回归；修改实机插件时用假 IgH 传输编译插件本体并测试争用、故障和目标对齐。只在用户授权的现场任务中连接硬件。
6. 在 Jazzy 环境执行 `bash ros2_ws/tools/verify_state_machine.sh`。若依赖或环境缺失，明确区分已执行、未执行与既有验证记录，不以静态检查替代运行验证。
7. 同步 README、状态协议和验证记录。README 使用新控制栈主入口，旧 SDO 演示保留在 `ros2_ws/LEGACY_ARM_CONTROL.md`。

## 故障停用与诊断

- 先确定错误来自资源管理器还是插件。`Not acceptable command interfaces combination` 可能是接口先被撤销、随后才停止控制器；不要仅修改插件的 stop 参数校验就宣称修复。
- 新 MOCK launch 才能启用 `supervised_fault_stop`。故障仍立即锁存、禁止命令、使位置反馈无效并停止推进周期；保留传输用于发布故障。管理器依次停轨迹控制器、广播器、硬件。独立使用插件默认仍返回 ERROR；实机错误路径不得套用此 MOCK 策略。
- 停止传输后不得把旧 active/fault_code 等作为当前值。`feedback_fresh=false`、当前硬件阶段 UNKNOWN、当前故障码 null，历史数据放 `last_observed_health` / `last_observed.*`，已观测故障原因单独保留。未知原因不能推断成故障码 5。
- `/system/state` 的 FAULT 原因必须保持至显式恢复。诊断优先显示仍新鲜的系统故障原因，明确标注过期的系统消息。
- 必须执行 `tools/verify_fault_delivery.py`：真实 ROS 下检查注入故障及对自己创建的 MOCK controller_manager 暂停 0.7 秒；检查轨迹不成功、无模式切换错误、旧值不冒充当前值、拒绝再次使能、显式恢复仅回 READY。不可对已有或实机进程发送暂停信号。

## 版本统一交付

- Windows 源码、虚拟机源码、install 产物可能来自不同版本。先核对实际路径与文件哈希，不能只看包名或历史测试数量。
- 打包完整 src、必要工具和文档，排除 build/install/log、缓存及虚拟环境。生成 SHA256 清单与 RELEASE_ID；同步到全新目录，保留旧工作空间和日志，不覆盖用户修改。
- 使用 `tools/build_release.sh` 和 `tools/ros_release.sh` 的干净环境，避免旧 AMENT_PREFIX_PATH/PYTHONPATH 污染；用 `--verify` 校验源码和安装资源。
- 新版必须 ready → enable → trajectory_demo；旧 longrun_vm.sh 硬编码 install-ubuntu，不得用于新版验收。
- 区分本地 Jazzy 验证、虚拟机部署验收和实机验收。主机没有直达虚拟机文件系统时交付可验证包与命令，不声称已替用户部署。

报告具体行为变化、实测测试结果和实机验证边界。假总线和 MOCK 通过不代表机械停机验收通过。
