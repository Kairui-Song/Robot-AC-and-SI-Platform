"""Mock-only ros2_control stack. Does not launch the legacy SDO command node."""
from pathlib import Path

import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, LogInfo, OpaqueFunction, RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def setup(context):
    share = Path(get_package_share_directory('linglong_control'))
    legacy_share = Path(get_package_share_directory('arm_control'))
    backend = LaunchConfiguration('backend').perform(context)
    if backend != 'mock':
        raise RuntimeError('Only backend:=mock is implemented. EtherCAT requires a separate verified PDO plugin.')
    mappings = {'backend': backend, 'nominal_period': '0.01'}
    for name in ('fault_after_cycles', 'dropout_after_cycles'):
        value = LaunchConfiguration(name).perform(context)
        if not value.isdecimal() or not 0 <= int(value) <= 1_000_000_000:
            raise RuntimeError(f'{name} must be an integer between 0 and 1000000000')
        mappings[name] = value
    description = xacro.process_file(str(share / 'urdf/arm_control.urdf.xacro'), mappings=mappings).toxml()
    robot = {'robot_description': ParameterValue(description, value_type=str)}
    manager = Node(
        package='controller_manager', executable='ros2_control_node', output='screen',
        parameters=[str(share / 'config/controllers.yaml')],
        remappings=[('~/robot_description', '/robot_description')])
    broadcaster = Node(
        package='controller_manager', executable='spawner', output='screen',
        arguments=['joint_state_broadcaster', '-c', '/controller_manager',
                   '--controller-manager-timeout', '30', '--switch-timeout', '10'])
    trajectory = Node(
        package='controller_manager', executable='spawner', output='screen',
        arguments=['arm_trajectory_controller', '-c', '/controller_manager',
                   '--controller-manager-timeout', '30', '--switch-timeout', '10'])

    def after_broadcaster(event, _context):
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason='joint_state_broadcaster failed'))]
        return [trajectory]

    def after_trajectory(event, _context):
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason='trajectory controller failed'))]
        return [LogInfo(msg='MOCK control ready: /arm_trajectory_controller/follow_joint_trajectory')]

    return [
        RegisterEventHandler(OnProcessExit(target_action=manager,
            on_exit=[EmitEvent(event=Shutdown(reason='controller_manager exited'))])),
        RegisterEventHandler(OnProcessExit(target_action=broadcaster, on_exit=after_broadcaster)),
        RegisterEventHandler(OnProcessExit(target_action=trajectory, on_exit=after_trajectory)),
        Node(package='robot_state_publisher', executable='robot_state_publisher', parameters=[robot]),
        manager, broadcaster,
        Node(package='linglong_control', executable='control_diagnostics', output='screen'),
        Node(package='rviz2', executable='rviz2',
             arguments=['-d', str(legacy_share / 'rviz/arm.rviz')],
             condition=IfCondition(LaunchConfiguration('rviz'))),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('backend', default_value='mock'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('fault_after_cycles', default_value='0'),
        DeclareLaunchArgument('dropout_after_cycles', default_value='0'),
        OpaqueFunction(function=setup),
    ])
