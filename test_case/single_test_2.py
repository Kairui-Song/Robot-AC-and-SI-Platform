import adapter as _adapter


def run_single_test(target, imu_port=None, serial_port=None, serial_baud=115200):
    """运行单项测试：target 可以是左腿/右腿/left_leg/right_leg 或 'IMU' 等。
    返回统一格式结果字典。
    """
    key = target.lower()
    if key in ('imu', 'imu_usb', 'imu_pose') or target == 'IMU':
        return _adapter.test_imu(imu_port=imu_port)

    # 其余视为 CAN 通道
    return _adapter.test_can_channel(
        target,
        serial_port=serial_port,
        serial_baud=serial_baud,
    )
