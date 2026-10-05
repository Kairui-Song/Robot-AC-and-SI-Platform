# Web、状态机与 ros2_control 接入

源代码链路：浏览器 `/ros-control` → Flask `/api/ros/*` → `ros_control_bridge.py` → 主控 `web_gateway` → `system_manager` 或 FollowJointTrajectory → ros2_control → mock / IgH PDO 插件。

默认启动硬件 INACTIVE、状态广播器 ACTIVE、轨迹控制器 INACTIVE。状态机读取新鲜反馈并确认 READY；点击使能后才进入 ENABLED。RUNNING 由正在执行的 Action 状态决定。任何使能/停用/恢复/关闭请求都由 `system_manager` 顺序执行并确认；HTTP 202 仅表示请求受理。

## Linux 主控构建与本机运行

在 Ubuntu 24.04 / ROS Jazzy 上：

```bash
source /opt/ros/jazzy/setup.bash
cd /path/to/project/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to linglong_control
source install/setup.bash
ros2 launch linglong_control control.launch.py backend:=mock rviz:=false
```

默认网关监听 `127.0.0.1:8091`。同机 Web 服务启动前设置：

```bash
export LINGLONG_ROS_URL=http://127.0.0.1:8091
cd /path/to/project
python3 app.py
```

打开 `/ros-control`，依次观察 READY → 使能 → ENABLED → 填写四轴偏移与时长 → 发送轨迹 → RUNNING → SUCCEEDED / ENABLED → 停用 → READY。

## Windows Web 对接远程 Linux 主控

主控启动前设置 `LINGLONG_ROS_BIND=0.0.0.0` 和非空 `LINGLONG_ROS_TOKEN`；Web 服务设置 `LINGLONG_ROS_URL=http://主控IP:8091` 与相同令牌。令牌只在服务环境变量中使用，不写入仓库或页面。仅将网关端口开放给 Web 服务所在机器；也可通过 SSH 隧道保持主控监听 loopback。

Windows PowerShell：

```powershell
$env:LINGLONG_ROS_URL = 'http://主控IP:8091'
$env:LINGLONG_ROS_TOKEN = '<与主控一致的令牌>'
python app.py
```

如果设置 `LINGLONG_ADMIN_TOKEN`，网页控制区需填写该管理员令牌；主控网关令牌与网页管理员令牌分别用于两段连接。

## 物理后端

沿用 [LEFT_ARM_HARDWARE.md](LEFT_ARM_HARDWARE.md) 的 IgH 构建与现场标定流程，使用已确认配置：

```bash
ros2 launch linglong_control control.launch.py \
  backend:=ethercat_left_arm hardware_config:=/absolute/path/to/commissioned.yaml rviz:=false
```

启动不会自动使能。Web 轨迹采用新鲜实测弧度，四轴必须全部出现，每轴相对偏移限制 ±0.05 rad，规划还检查标定机械范围和速度。实机故障锁存后拒绝自动复位；纠正原因并按现场流程重启控制栈。关闭或停用服务确认的是软件/硬件生命周期结果，不是机械停止的独立证明。

设置 `LINGLONG_ROS_URL` 后，网页旧直连预检与运动基准被服务器拒绝；不会在 ROS 离线时回退到 EtherCAT CLI。外部维护脚本仍需现场独占管理，不应与 ROS 主站同时运行。

## 接口和反馈

- `GET /api/ros/state`：系统状态、后端、新鲜关节反馈、限位、最近轨迹结果。
- `POST /api/ros/enable|disable|recover|shutdown`：空 JSON 对象，转发 `/system/*` Trigger 服务。
- `POST /api/ros/trajectory`：`{"offsets":[0.01,0,0,0],"duration":6}`，顺序 joint_1/2/3/5，转发 FollowJointTrajectory Action。
- `POST /api/ros/cancel`：只取消网关持有的当前 Action；等待结果确认 CANCELLED。
- 主控 HTTP 接口使用相同命令路径，移除 `/api/ros` 前缀；用于服务间连接。

网关、系统状态或反馈超时后，页面显示 UNKNOWN/反馈未知并拒绝运动。HTTP 超时不自动重试；应先检查系统状态。健康报文保留 `last_observed_*` 历史信息，过期 ACTIVE/零故障数据不会显示为当前状态。

## 验证

```bash
export PYTHONPATH="$PWD/src/linglong_control:$PWD/src/arm_control:$PYTHONPATH"
python3 -m pytest src/linglong_control/test src/arm_control/test -q
colcon test --packages-select linglong_control arm_control
colcon test-result --verbose
python3 tools/verify_system_state.py
python3 tools/verify_fault_delivery.py
python3 tools/verify_web_integration.py
```

`verify_web_integration.py` 创建独立 ROS domain、随机 loopback 端口与临时令牌，只选择 mock；验证 READY、使能、四轴 Action、取消、停用、故障锁存、恢复与关闭。结果和本次 launch 日志写入新的 `verification/web-integration-*` 目录。

本次开发机的 WSL 没有 `/opt/ros/jazzy`，因此本机验证覆盖 Python/HTTP/Flask 适配链和 ROS 无关 C++ 核心；ROS 插件构建、DDS、控制器实际运行及物理设备联调需在目标主控执行上述命令。旧交付包和旧验证记录不代表本次源码已通过运行验收。
