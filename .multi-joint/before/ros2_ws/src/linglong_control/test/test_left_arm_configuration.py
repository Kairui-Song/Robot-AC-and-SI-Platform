from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import xacro
import yaml

from linglong_control_tools.left_arm_configuration import NAMES, physical_description, validate
from linglong_control_tools.health import HealthMonitor, HEALTH_KEYS

PACKAGE = Path(__file__).resolve().parents[1]


def configured():
    config = yaml.safe_load((PACKAGE / 'config/left_arm_hardware.yaml').read_text(encoding='utf-8'))
    for flag in ('calibration_confirmed', 'pdo_mapping_confirmed', 'stop_behavior_confirmed'):
        config[flag] = True
    config['watchdog_intervals'] = 1000
    for joint in config['joints'].values():
        joint['counts_per_radian'] = 100000.0
        joint['velocity_counts_per_rad_s'] = 100000.0
    config['joints']['joint_2']['counts_per_radian'] = -100000.0
    return config


def test_template_cannot_enable_hardware():
    template = yaml.safe_load((PACKAGE / 'config/left_arm_hardware.yaml').read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='calibration_confirmed'):
        validate(template)


@pytest.mark.parametrize('key,value', [
    ('calibration_confirmed', False), ('pdo_mapping_confirmed', 'true'),
    ('stop_behavior_confirmed', False), ('master_index', -1), ('update_rate', 0),
    ('update_rate', 100.5), ('cycle_timeout', float('nan')), ('cycle_timeout', .001),
    ('vendor_id', 0x03456789), ('product_code', 0), ('watchdog_intervals', 0),
    ('dc_assign_activate', 65536), ('startup_timeout', 0),
])
def test_reject_wrong_hardware_and_unconfirmed_settings(key, value):
    config = configured()
    config[key] = value
    with pytest.raises(ValueError):
        validate(config)


@pytest.mark.parametrize('key,value', [
    ('slave_position', 4), ('counts_per_radian', 0), ('counts_per_radian', 1e20),
    ('velocity_counts_per_rad_s', 0), ('zero_counts', float('inf')),
    ('lower', 2), ('max_command_step', -1), ('max_following_error', 0),
    ('max_velocity', False),
])
def test_reject_bad_joint_calibration(key, value):
    config = deepcopy(configured())
    config['joints']['joint_5'][key] = value
    with pytest.raises(ValueError):
        validate(config)


def test_actual_description_routes_all_left_arm_joints(tmp_path):
    source = (PACKAGE / 'urdf/arm_control.urdf.xacro').read_text(encoding='utf-8')
    source = source.replace('$(find arm_control)', (PACKAGE.parent / 'arm_control').as_posix())
    path = tmp_path / 'arm.xacro'
    path.write_text(source, encoding='utf-8')
    mock_xml = xacro.process_file(str(path)).toxml()
    config = configured()
    config['joints']['joint_1']['lower'] = -.7
    config['update_rate'] = 250
    root = ET.fromstring(physical_description(mock_xml, config))
    system = root.find('ros2_control')
    assert system.find('hardware/plugin').text == 'linglong_control/LeftArmSystem'
    assert float(system.find("hardware/param[@name='nominal_period']").text) == .004
    assert [j.attrib['name'] for j in system.findall('joint')] == list(NAMES)
    assert [j.find("param[@name='slave_position']").text for j in system.findall('joint')] == ['1', '2', '3', '5']
    assert root.find("joint[@name='joint_1']/limit").attrib['lower'] == '-0.7'
    assert not system.findall("joint/param[@name='initial_position']")
    assert system.find("joint[@name='joint_2']/param[@name='counts_per_radian']").text == '-100000.0'
    controllers = yaml.safe_load((PACKAGE / 'config/controllers.yaml').read_text(encoding='utf-8'))
    params = controllers['arm_trajectory_controller']['ros__parameters']
    assert params['joints'] == list(NAMES)
    assert params['allow_partial_joints_goal'] is False


def test_physical_health_is_not_misreported_as_mock():
    monitor = HealthMonitor(expected_backend='ethercat_left_arm')
    names = [*NAMES, 'control_health']
    values = [(['position', 'velocity'], [0, 0]) for _ in NAMES]
    values.append((HEALTH_KEYS, [0, 1, 0, 1, .01, .01, 0, 0]))
    monitor.receive(names, values, 1)
    assert monitor.status(1) == (0, 'LEFT_ARM EtherCAT PDO feedback running')
    assert monitor.status(2)[0] == 3
    mock = HealthMonitor()
    mock.receive(names, values, 1)
    assert mock.status(1)[0] == 2
    values[-1] = (HEALTH_KEYS, [0, 0, 10, 2, .01, .01, 0, 0])
    monitor.receive(names, values, 2)
    assert 'drive state/mode' in monitor.status(2)[1]
