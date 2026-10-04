# Jazzy 统一交付与虚拟机验收

发行标识：`linglong-jazzy-20261001-fault-stop-v1`。当前虚拟机中的旧版无系统状态机，
不能仅覆盖几份 Python 文件；请把完整发行包解压到全新目录，保留原项目和验证日志。

## 从交付包开始

在 Ubuntu 安装好 ROS 2 Jazzy、colcon、rosdep 后执行。不要复用原 install-ubuntu/install-vm。

```bash
mkdir -p ~/linglong-releases
cd ~/linglong-releases
python3 -m zipfile -e ~/Downloads/linglong-jazzy-20261001-fault-stop-v1.zip .
cd linglong-jazzy-20261001-fault-stop-v1/ros2_ws
bash tools/build_release.sh --install-deps
bash tools/ros_release.sh --test
```

构建入口先校验 SOURCE_MANIFEST.json，使用普通安装并运行 colcon 测试。
运行入口清除继承的 ROS/Python 前缀，只加载 Jazzy 与本发行 install-release，
核对安装位置和 RELEASE_ID。`--verify` 额外校验源码、已安装模块、脚本和模型文件。
源码被修改后校验应失败；开发修改需重新生成发行清单，不能跳过校验伪装同一版本。

自动联调使用隔离 domain 94，会自行启动并停止自己的 MOCK 进程，不开 RViz。
包含正常运动/取消/停用/恢复，以及注入故障和 0.7 秒周期停顿的负向测试。
负向测试必须观察到 FAULT 才通过，不是“消除 FAULT”。日志和 JSON 保存在 verification。
IgH 假总线测试需要另行提供官方头文件；默认交付构建不代表实机插件已验证。

## 人工演示

终端 A（进入本发行 ros2_ws 目录）：

```bash
bash tools/ros_release.sh --verify
bash tools/ros_release.sh launch linglong_control control.launch.py backend:=mock rviz:=true
```

终端 B（同一目录）：

```bash
bash tools/ros_release.sh run linglong_control system_transition ready
bash tools/ros_release.sh run linglong_control system_transition enable
bash tools/ros_release.sh run linglong_control trajectory_demo
bash tools/ros_release.sh run linglong_control system_transition disable
bash tools/ros_release.sh topic echo /system/state --once
```

旧 `tools/longrun_vm.sh` 硬编码 install-ubuntu，不能用于这个版本。两个终端均使用新入口，
不要同时运行旧 launch。新版默认 READY、不自动使能；SHUTDOWN 是终态，需要重启 launch。

## 验收范围

- 故障后禁止运动、按顺序停控制器/广播器/硬件，日志中无接口组合/模式切换错误。
- 反馈过期时不展示旧 active/零故障为当前值；历史原因保留，未知原因不推断。
- explicit recover 只回 READY；必须再次 enable 才能运动。
- 完整包+哈希+安装路径一致才算版本统一；本机打包不等于虚拟机已部署。
- 长时间稳定性、宿主机长停顿根因和实机通信/负载/制动验收仍需分别完成。
