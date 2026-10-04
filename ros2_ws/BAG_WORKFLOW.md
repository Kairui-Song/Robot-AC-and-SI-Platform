# 左臂录制、归档、分析与回放验收

实现入口：`ros2 run linglong_control bag_session`。v1 面向正常 mock 基线；默认 observe 不发动作，显式 wave 才通过现有标准 Action 执行一次四关节波浪动作。
这是一套已实现、待在用户 Ubuntu/Jazzy 中运行验收的流程；当前没有实际录包或回放通过记录。

## 1. 在已有虚拟机中构建并启动

在项目 `ros2_ws` 目录执行，不需要本工具安装任何环境：

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
export ROS_DOMAIN_ID=87
ros2 launch linglong_control left_arm.launch.py backend:=mock rviz:=false
```

另一个终端进入同一工作空间，source 同一环境并设置同一 domain：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=87
ros2 run linglong_control bag_session record --scenario wave --duration 20
```

只观察已有状态用 `--scenario observe`。duration 范围 10–120 s，从录包必需话题订阅就绪开始计时；wave 推荐至少 20 s。工具不启动控制栈，错误 domain、未启动、反馈不健康、TF 不可用都会失败，不会默认为模拟成功。
初次使用若环境缺少 package.xml 声明的 rosbag2_py、sqlite3 storage、TF2 等依赖，按错误补齐你现有虚拟机环境；工具不会自行安装。

## 2. 自动归档

输出 `verification/bags/record-UTC时间-随机ID/`，每次新建，已有证据不覆盖：

- `bag/`：sqlite3 rosbag 和 metadata.yaml，状态白名单包含隐藏 Action status/feedback。
- `config/`、`launch/`、`urdf/`、`source/`、package.xml：实际使用安装包中的配置及工具代码快照。
- `*.parameters.yaml`：四个节点的实际参数；robot_state_publisher 导出含展开模型。
- `before.json`：录制前控制器、硬件、QoS 和健康证据；`tf.json`：TF2 的 base_link ← link_5 最新可用变换。
- wave 模式的 `goal.json`：完整四关节轨迹点；`goal.accepted.json`：接受结果及 UUID；`goal.result.json`：同 UUID 的成功结果和终点误差；`motion.log` 保存客户端输出/错误。
- `record.log`、参数/TF/快照相关日志和 `analysis.json`：执行与分析证据。
- `manifest.json`：场景、domain、环境标识、mock 插件哈希、执行命令、归档文件 SHA256、完成/失败状态及错误。

录制和回放都尝试清理所有子进程并保留失败归档。`state=complete` 只表示流程生成完整结果，还必须查看 `acceptance_passed`。`state=failed`、异常退出或不存在 metadata 时不得计为通过。
SHA256 用于检测归档意外变化，不是签名认证。源归档封存后不要添加报告；新分析输出到外部路径，回放写新目录。

## 3. 离线分析真实 bag

无需启动控制栈；仍需 source 已有 ROS 环境以提供 rosbag reader 和消息类型：

```bash
ros2 run linglong_control bag_session analyze \
  verification/bags/record-实际目录 \
  --output verification/analysis-rerun-001.json
```

先检查归档文件清单和哈希，再逐条反序列化分析，不把全部 bag 装入内存。主要判据：

- 必需话题类型和样本数量、至少 2 s 覆盖；连续状态间隙不超过 0.5 s，不能提前停止后仍判健康。
- 四关节名称、有限位置/速度；mock、active、无故障且控制周期持续前进。
- controller reference/feedback 最大误差不超过 0.15 rad；这是录制证据门槛，不是硬件制动或最终定位精度。
- ROS header 正值且严格递增；接收时间不回退。报告接收间隙，不能当作 DDS 丢包计数。
- `linglong/control` 诊断为 OK；TF 四条模型边齐全、无多父节点/环、变换数值有效且四元数归一。
- wave 必须在 bag 中找到同一 Goal UUID 的 SUCCEEDED 状态，并有对应客户端接受和结果文件；旧 Goal 的保留状态不能替代。

当前 URDF 没有固定关节，因此 `/tf_static` 是可选项。Action feedback 也是记录项而非最低样本门槛；Action 接受与 result 来自客户端独立文件，未通过 rosbag 服务事件录制它们。
本工具按正常运行判据分析，故障注入出现 ERROR/STALE 应失败；不自动把失败记录归因为 EtherCAT 故障。

## 4. 独立 domain 回放与再次录制

```bash
ros2 run linglong_control bag_session replay-verify \
  verification/bags/record-实际目录 --domain 88
```

88 必须与当前 domain 和源归档 domain 不同，并且未被其他节点占用。控制栈可继续在 87 运行，但不要在 88 启动任何其他应用。
回放只发布白名单状态，全部映射到 `/replay/...`；没有运动命令、服务事件或 Action 请求的再执行。工具不加载硬件，不发布 `/clock`。
先启动 recorder 和暂停的 player，确认全部有数据的话题已被 recorder 订阅，再调用唯一的 Resume 服务；固定睡几秒不作为订阅就绪证据。

输出 `verification/replays/replay-.../`：回放 bag、player/recorder 日志、两侧分析报告、`comparison.json`、manifest 及源 manifest 的哈希。
通过条件：源正常基线检查通过、播放/录制正常退出，以及**每话题消息数量、类型、规范化消息内容的有序摘要完全一致**。丢失、重复、内容变化或话题内重排都会失败并返回非零。
这验证录包内容经 DDS 回放后的保真性；忽略新接收时间、跨话题交错顺序，不证明历史实时性能，也不证明算法或动作重新执行结果相同。
回放分析中的接收时间指标可以因调度不同而变化，所以最终判据在 comparison.json，不能把 replay-analysis.json 的实时接收间隙当成原系统性能。

## 失败处理与边界

缺少消息类型、storage 插件、QoS 不匹配、发现超时、进程异常、缺帧、错误 UUID、哈希变化都返回失败，保留已有日志。若回放摘要不一致，先比较消息数量、QoS 与 recorder/player 日志；不通过放宽为“文件存在”解决问题。
录制需单一模型/关节状态发布者；本版不提供任意 namespace、多臂或物理后端正常验收 profile。模型尺寸仍未标定，TF 流程通过不代表机械几何准确。
当前尚未实现录包分片、磁盘限额/保留策略和故障专用判据；单次时长有界，但长期归档空间由使用者管理。

API 依据：ROS2 官方 [Jazzy record CLI](https://github.com/ros2/rosbag2/blob/jazzy/ros2bag/ros2bag/verb/record.py)、[play CLI](https://github.com/ros2/rosbag2/blob/jazzy/ros2bag/ros2bag/verb/play.py)、[SequentialReader 示例测试](https://github.com/ros2/rosbag2/blob/jazzy/rosbag2_py/test/test_sequential_reader.py)。实现仍需目标 Jazzy 安装的实际集成验证。
