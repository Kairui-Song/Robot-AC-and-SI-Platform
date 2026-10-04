# 左臂 EtherCAT 网页控制部署说明

## 1. 首次安全要求

- 机械臂悬空，运动范围内无人、无障碍物。
- 急停按钮必须在现场人员手边。
- 首次测试先在“系统配置”中把点动幅度改为 `1000`。
- 确认 `sudo ethercat -m 0 slaves` 显示 p1、p2、p3、p5 四个左臂伺服从站。

## 2. 将受控程序部署到主控

Ubuntu 网页主机连接 `butler3-5G` 后，在项目目录执行：

```bash
scp ./controller/ethercat_left_arm_test.py enpht@192.168.1.201:/tmp/
scp ./controller/install_left_arm_service.sh enpht@192.168.1.201:/tmp/
scp ./controller/control_benchmark.py enpht@192.168.1.201:/tmp/
scp ./controller/dance_flow.sh enpht@192.168.1.201:/tmp/
ssh enpht@192.168.1.201
```

登录主控后执行：

```bash
cd /tmp
chmod +x install_left_arm_service.sh
./install_left_arm_service.sh ethercat_left_arm_test.py control_benchmark.py dance_flow.sh
ls -l /opt/linglong/ethercat_left_arm_test.py /opt/linglong/dance_flow.sh
command -v bc
sudo ethercat -m 0 slaves
```

## 3. 配置 SSH 密钥

在 Ubuntu 网页主机终端执行：

```bash
ssh-keygen -t ed25519
ssh-copy-id -i ~/.ssh/id_ed25519.pub enpht@192.168.1.201
ssh enpht@192.168.1.201
```

最后一条命令应当不再询问 SSH 登录密码。

## 4. 网页配置

1. 启动网页程序并进入“系统配置”。
2. 若网页就在主控上运行，选择“主控本机运行”；只有网页在另一台电脑上运行时才选择“电脑运行 · SSH”。
3. 主控 IP 填 `192.168.1.201`，用户填 `enpht`。
4. SSH 私钥路径填当前用户的 `id_ed25519` 完整路径。
5. 舞蹈脚本路径保持 `/opt/linglong/dance_flow.sh`。
6. sudo 密码已配置为 `enpht`；Ubuntu 下配置文件权限为 `0600`，页面不会回显密码。
7. 首次将点动幅度设为 `1000`，保存配置。

## 5. 首次测试

进入“单电机测试”，点击“左机械臂 · dance_flow 动作测试”。网页程序会通过 SSH 在恩菲特主控上执行：

```text
sudo bash /opt/linglong/dance_flow.sh 200
```

脚本使能 p1、p2、p3、p5，执行与原 `dance_flow(1).sh` 相同的波浪位置变化，默认运行 200 步（约 6 秒，不含 EtherCAT 命令开销），结束、报错或被停止时自动对四个从站发送失能。页面会显示连接、执行进度及最终状态。

完成执行器链路验证后，可进入“主控性能测试”，先按关节1、±1000、10 Hz、20次运行闭环基准。原始JSON和CSV保存在网页程序的 `logs/benchmarks` 目录。EtherCAT CLI测试包含命令行进程开销，后续接入Robot SDK后由SDK适配器承担高频测试。

## 6. 主控本机模式

若 Flask 网页程序直接运行在恩菲特主控，将运行模式改为“主控本机运行”。程序仍调用相同的受控测试脚本和 sudo 密码，不经过 SSH。

## 7. 停止与故障

- 点击“停止左臂测试并失能”或左侧“急停”，网页会终止执行链路。
- 主控脚本收到终止或 SSH 挂断信号后，会尝试恢复原位并向 p1、p2、p3、p5发送失能。
- 软件停止不能替代物理急停。网络中断时应立即使用物理急停。
