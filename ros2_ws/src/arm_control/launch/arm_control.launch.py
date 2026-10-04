from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory('arm_control'))
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=str(share / 'config/arm_control.yaml')),
        DeclareLaunchArgument('backend', default_value='mock'),
        DeclareLaunchArgument('rviz', default_value='true'),
        Node(package='arm_control', executable='arm_control_node', name='arm_control',
             output='screen', parameters=[LaunchConfiguration('params_file'),
                                         {'backend': LaunchConfiguration('backend')}]),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': (share / 'urdf/arm.urdf').read_text()}]),
        Node(package='rviz2', executable='rviz2',
             arguments=['-d', str(share / 'rviz/arm.rviz')],
             condition=IfCondition(LaunchConfiguration('rviz'))),
    ])
