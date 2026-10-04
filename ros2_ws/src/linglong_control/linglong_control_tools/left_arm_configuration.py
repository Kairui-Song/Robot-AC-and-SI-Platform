"""Validate field calibration before generating the physical left-arm description."""
import math
import xml.etree.ElementTree as ET

from linglong_control_tools.interfaces import JOINT_NAMES as NAMES
SLAVES = (1, 2, 3, 5)
BUS_FIELDS = ('link_up', 'working_counter', 'wc_state', 'feedback_valid', 'dc_enabled',
              'first_fault_slave', 'first_fault_cycle', 'last_good_cycle', 'state_valid')
SLAVE_FIELDS = ('al_state', 'online', 'operational', 'status_word', 'mode_display', 'state_valid', 'sample_valid')


def numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def validate(config):
    if not isinstance(config, dict):
        raise ValueError('left_arm hardware configuration must be a mapping')
    for flag in ('calibration_confirmed', 'pdo_mapping_confirmed', 'stop_behavior_confirmed'):
        if config.get(flag) is not True:
            raise ValueError(f'{flag} must be true after field commissioning')
    ranges = {'master_index': (0, 255), 'update_rate': (50, 1000),
              'dc_assign_activate': (0, 65535), 'watchdog_divider': (0, 65535),
              'watchdog_intervals': (1, 65535)}
    for name, (low, high) in ranges.items():
        value = numeric(config.get(name), name)
        if not low <= value <= high or int(value) != value:
            raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    if config.get('vendor_id') != 0x1097 or config.get('product_code') != 0x2406:
        raise ValueError('Expected existing EYOU left arm: vendor 0x1097 / product 0x2406')
    period = 1 / config['update_rate']
    timeout = numeric(config.get('cycle_timeout'), 'cycle_timeout')
    if not period < timeout <= 0.5:
        raise ValueError('cycle_timeout must exceed one cycle and be <= 0.5 s')
    if not 1 <= numeric(config.get('startup_timeout'), 'startup_timeout') <= 30:
        raise ValueError('startup_timeout must be in [1, 30] seconds')
    joints = config.get('joints')
    if not isinstance(joints, dict) or set(joints) != set(NAMES):
        raise ValueError('Require exactly joint_1/2/3/5')
    for name, slave in zip(NAMES, SLAVES):
        joint = joints[name]
        if not isinstance(joint, dict) or joint.get('slave_position') != slave:
            raise ValueError(f'{name} must map to deployed slave {slave}')
        for key in ('counts_per_radian', 'zero_counts', 'velocity_counts_per_rad_s',
                    'lower', 'upper', 'max_velocity', 'max_command_step', 'max_following_error'):
            numeric(joint.get(key), f'{name}.{key}')
        if joint['counts_per_radian'] == 0 or joint['velocity_counts_per_rad_s'] == 0:
            raise ValueError(f'{name}: measured position/velocity scales are required')
        if joint['lower'] >= joint['upper']:
            raise ValueError(f'{name}: lower must be below upper')
        if any(joint[k] <= 0 for k in ('max_velocity', 'max_command_step', 'max_following_error')):
            raise ValueError(f'{name}: limits must be positive')
        for bound in ('lower', 'upper'):
            count = joint['zero_counts'] + joint['counts_per_radian'] * joint[bound]
            if not math.isfinite(count) or not -(2**31) <= count <= 2**31 - 1:
                raise ValueError(f'{name}: calibrated range exceeds int32')
    return config


def physical_description(mock_xml, config):
    """Reuse yesterday's four-joint model/controller names, replace only hardware."""
    validate(config)
    root = ET.fromstring(mock_xml)
    system = root.find('ros2_control')
    system.set('name', 'LinglongLeftArmSystem')
    hardware = system.find('hardware')
    hardware.clear()
    ET.SubElement(hardware, 'plugin').text = 'linglong_control/LeftArmSystem'
    params = {key: config[key] for key in ('master_index', 'vendor_id', 'product_code',
              'dc_assign_activate', 'watchdog_divider', 'watchdog_intervals',
              'cycle_timeout', 'startup_timeout')}
    params.update(backend='ethercat_left_arm', commissioning_confirmed='true',
                  nominal_period=1 / config['update_rate'])
    for key, value in params.items():
        ET.SubElement(hardware, 'param', name=key).text = str(value)
    for sensor_name, fields in [('ethercat_bus', BUS_FIELDS),
                                *[(f'ethercat_slave_{p}', SLAVE_FIELDS) for p in SLAVES]]:
        sensor = ET.SubElement(system, 'sensor', name=sensor_name)
        for field in fields:
            ET.SubElement(sensor, 'state_interface', name=field)
    for name in NAMES:
        joint = system.find(f"joint[@name='{name}']")
        for param in list(joint.findall('param')):
            joint.remove(param)
        values = config['joints'][name]
        for key, value in values.items():
            ET.SubElement(joint, 'param', name=key).text = str(value)
        command = joint.find('command_interface')
        command.find("param[@name='min']").text = str(values['lower'])
        command.find("param[@name='max']").text = str(values['upper'])
        limit = root.find(f"joint[@name='{name}']/limit")
        limit.set('lower', str(values['lower']))
        limit.set('upper', str(values['upper']))
        limit.set('velocity', str(values['max_velocity']))
    return ET.tostring(root, encoding='unicode')
