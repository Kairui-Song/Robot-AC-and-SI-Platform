"""Explicit four-joint entry point; shares controller ownership with control.launch.py."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    share = Path(get_package_share_directory('linglong_control'))
    names = ('backend', 'hardware_config', 'rviz')
    return LaunchDescription([
        DeclareLaunchArgument('backend', default_value='mock'),
        DeclareLaunchArgument('hardware_config', default_value=''),
        DeclareLaunchArgument('rviz', default_value='true'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share / 'launch/control.launch.py')),
            launch_arguments={name: LaunchConfiguration(name) for name in names}.items()),
    ])
