import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/install-release/arm_control'
