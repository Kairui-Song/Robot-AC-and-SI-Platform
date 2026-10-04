# linglong_1025 一键产线自检 UI

ROS2 控制栈入口：[`ros2_ws/ROS2_CONTROL.md`](ros2_ws/ROS2_CONTROL.md)。新增 `linglong_control`，提供 C++ ros2_control SystemInterface、四关节标准轨迹 Action、生命周期、限位/故障锁存和诊断；本阶段仅支持模拟，真机 PDO 接入需按现场配置继续实现。原 `arm_control` 单点 SDO 演示说明保留在 [`ros2_ws/README.md`](ros2_ws/README.md)。

新增只读 `fault_snapshot`，采集控制器、硬件接口、目标/反馈和 ROS 通信证据，保存分层故障 JSON；已集成到模拟故障验收脚本，不自动控制或复位设备。

已新增[模拟可靠性与性能基线](ros2_ws/SIMULATION_BASELINE_20260925.md)：加速仿真、随机故障/恢复及普通调度实测，附原始数据和一键复现入口；明确区分模拟结果与未完成的真机验收。

快速说明：本项目在主控本机运行，提供网页 UI 用于对 5 路 CAN 总线（左腿、右腿、左臂、右臂、头部）和 IMU USB 姿态单元进行一键自检。

主要新增点：
- 使用 `Flask` + `Flask-SocketIO` 提供后端通信与事件推送。
- 新增 `imu_reader.py`：读取 IMU（若无硬件则模拟数据），通过 SocketIO 推送 `imu_data`。
- 新增 `can_control.py`、`tester.py`：封装 CAN 发送/监听逻辑（默认尝试调用本机已有硬件 API，如 `motor_control` 或 `canbus`，若不存在则模拟）。
- 前端在 `templates/single_motor_test.html` 中新增测试按钮，`static/js/app.js` 负责触发测试并显示结果。

运行说明（在主控主机上）：

1. 创建虚拟环境并安装依赖：

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

2. 可选：设置 Ubuntu 下的 IMU 串口环境变量：

```bash
export IMU_PORT=/dev/ttyUSB0
export IMU_BAUD=115200
```

3. 启动服务：

```bash
# 方式 A：在普通浏览器中打开（开发/调试）
python3 app.py

# 方式 B：在主控本机以原生窗口运行（HDMI + 鼠标键盘，推荐线下产线使用）
python3 run_gui.py
```

4. 在测试主机打开浏览器访问 http://localhost:5000，进入“单电机测试”页面，点击对应测试按钮开始一键自检。

5. 若需要直接启动整合后的界面，执行 `./start_ubuntu.sh`。

## 生产运行安全开关

- 串口/CAN 硬件不可用时，测试默认失败，不会再伪造通过结果。仅用于开发演示时才设置 `LINGLONG_SIMULATION_MODE=true`。
- 未配置、断开或超时的 IMU 会显示为离线；只有显式模拟模式才推送模拟姿态数据。
- 单电机预检和 JE 主控基准测试共用 EtherCAT Master0 互斥锁，同一时刻只能运行一个。
- 若要保护网页中的 EtherCAT 配置写入接口，请在服务端设置 `LINGLONG_ADMIN_TOKEN`；写入请求须携带同值的 `X-Linglong-Admin-Token` HTTP 请求头。生产环境还应设置 `LINGLONG_ALLOWED_ORIGINS` 为允许访问的网页来源。

注意：当前集成已接入 [peak_driver_bridge.py](peak_driver_bridge.py) 与 [peak-linux-driver-8.20.0/scripts/quanbu_tongshi.py](../peak-linux-driver-8.20.0/scripts/quanbu_tongshi.py) 的 CAN 逻辑；单电机测试按钮会通过 `usb-can0` 通道调用驱动脚本。若硬件环境不同，请修改 `peak_driver_bridge.py` 中的 `channel` 参数或脚本路径。

## 多型号单电机安全预检

“单电机测试”页面现提供泰科、意优、达妙和德昌电机档案。统一测试按钮只启动 IgH `ecrt` 只读预检，不切换 OP、不注册 PDO、不发送控制字。未知型号的 Vendor ID、Product Code 和 PDO 保持为空，不能因此获得动作许可。

在恩菲特主控部署只读程序：

```bash
scp controller/single_motor_preflight.c controller/install_single_motor_preflight.sh enpht@192.168.1.201:/tmp/
ssh enpht@192.168.1.201
cd /tmp
chmod +x install_single_motor_preflight.sh
./install_single_motor_preflight.sh single_motor_preflight.c
```

程序安装为 `/opt/linglong/bin/controller_test_client`，必须在主控上使用与现有 IgH Master 匹配的 `ecrt.h` 和 `libethercat` 编译。只有主控信息采集完成、链路在线且总线上恰好读取到一个从站时测试才通过；通过也不代表允许电机动作。

## JE 主控通信观察程序部署

网页默认使用 `/opt/linglong/bin/je_single_motor_test_v2`。该程序持续观察 Master0，并保持控制字为禁用、目标位置为实际位置；它不是运动基准工具。

```bash
scp controller/je_single_motor_test_v2.cpp controller/install_je_single_motor_test_v2.sh enpht@192.168.1.201:/tmp/
ssh enpht@192.168.1.201
cd /tmp
chmod +x install_je_single_motor_test_v2.sh
./install_je_single_motor_test_v2.sh je_single_motor_test_v2.cpp
```

安装后在 sudoers 中只为该固定可执行文件配置 NOPASSWD，并核对脚本输出的 SHA-256。`control_benchmark.py` 会写入目标位置，只能作为经现场安全确认后的维护工具，不应配置为默认网页测试程序。
