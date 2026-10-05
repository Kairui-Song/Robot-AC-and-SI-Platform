"""Shared trajectory stack: mock or the commissioned four-joint left-arm PDO plugin."""
from pathlib import Path

import xacro
import yaml
from linglong_control_tools.left_arm_configuration import physical_description, validate
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
    if backend not in ('mock', 'ethercat_left_arm'):
        raise RuntimeError('backend must be mock or ethercat_left_arm')
    mappings = {'backend': 'mock', 'nominal_period': '0.01'}
    for name in ('fault_after_cycles', 'dropout_after_cycles'):
        value = LaunchConfiguration(name).perform(context)
        if not value.isdecimal() or not 0 <= int(value) <= 1_000_000_000:
            raise RuntimeError(f'{name} must be an integer between 0 and 1000000000')
        mappings[name] = value
    description = xacro.process_file(str(share / 'urdf/arm_control.urdf.xacro'), mappings=mappings).toxml()
    rate = 100
    if backend == 'ethercat_left_arm':
        if any(int(mappings[name]) for name in ('fault_after_cycles', 'dropout_after_cycles')):
            raise RuntimeError('Mock fault injection is not permitted on physical hardware')
        path = LaunchConfiguration('hardware_config').perform(context)
        if not path:
            raise RuntimeError('ethercat_left_arm requires hardware_config:=/absolute/path/to/calibration.yaml')
        with Path(path).open(encoding='utf-8') as stream:
            config = validate(yaml.safe_load(stream))
        description = physical_description(description, config)
        rate = int(config['update_rate'])
    robot = {'robot_description': ParameterValue(description, value_type=str)}
    hardware_name = 'LinglongSimSystem' if backend == 'mock' else 'LinglongLeftArmSystem'
    manager = Node(
        package='controller_manager', executable='ros2_control_node', output='screen',
        parameters=[str(share / 'config/controllers.yaml'), {'update_rate': rate,
            'hardware_components_initial_state.inactive': [hardware_name]}],
        remappings=[('~/robot_description', '/robot_description')])
    broadcaster = Node(
        package='controller_manager', executable='spawner', output='screen',
        arguments=['joint_state_broadcaster', '-c', '/controller_manager',
                   '--controller-manager-timeout', '30', '--switch-timeout', '10'])
    trajectory = Node(
        package='controller_manager', executable='spawner', output='screen',
        arguments=['arm_trajectory_controller', '-c', '/controller_manager',
                   '--inactive',
                   '--controller-manager-timeout', '30', '--switch-timeout', '10'])
    supervisor = Node(package='linglong_control', executable='system_manager', output='screen',
        parameters=[{'backend': backend, 'hardware_name': hardware_name, 'nominal_period': 1.0 / rate}])
    gateway = Node(package='linglong_control', executable='web_gateway', output='screen',
        parameters=[{'backend': backend, 'robot_description': description}],
        condition=IfCondition(LaunchConfiguration('web_gateway')))

    def after_broadcaster(event, _context):
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason='joint_state_broadcaster failed'))]
        return [trajectory]

    def after_trajectory(event, _context):
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason='trajectory controller failed'))]
        return [LogInfo(msg=f'{backend} configured; wait for /system/state READY then call /system/enable')]

    return [
        RegisterEventHandler(OnProcessExit(target_action=manager,
            on_exit=[EmitEvent(event=Shutdown(reason='controller_manager exited'))])),
        RegisterEventHandler(OnProcessExit(target_action=broadcaster, on_exit=after_broadcaster)),
        RegisterEventHandler(OnProcessExit(target_action=trajectory, on_exit=after_trajectory)),
        Node(package='robot_state_publisher', executable='robot_state_publisher', parameters=[robot]),
        manager, broadcaster,
        RegisterEventHandler(OnProcessExit(target_action=supervisor,
            on_exit=[EmitEvent(event=Shutdown(reason='system supervisor exited'))])),
        RegisterEventHandler(OnProcessExit(target_action=gateway,
            on_exit=[EmitEvent(event=Shutdown(reason='Web gateway exited'))])),
        supervisor, gateway,
        Node(package='linglong_control', executable='control_diagnostics', output='screen',
             parameters=[{'expected_backend': backend, 'nominal_period': 1.0 / rate}]),
        Node(package='rviz2', executable='rviz2',
             arguments=['-d', str(legacy_share / 'rviz/arm.rviz')],
             condition=IfCondition(LaunchConfiguration('rviz'))),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('backend', default_value='mock'),
        DeclareLaunchArgument('hardware_config', default_value=''),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('web_gateway', default_value='true'),
        DeclareLaunchArgument('fault_after_cycles', default_value='0'),
        DeclareLaunchArgument('dropout_after_cycles', default_value='0'),
        OpaqueFunction(function=setup),
    ])
