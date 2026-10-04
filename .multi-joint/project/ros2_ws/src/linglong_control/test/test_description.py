"""Expand the real xacro offline and check cross-file controller/resource agreement."""
from pathlib import Path
import xml.etree.ElementTree as ET

import xacro
import yaml

PACKAGE = Path(__file__).resolve().parents[1]


def test_description_matches_controller_interfaces(tmp_path):
    # Resolve just the package lookup outside ROS; everything else uses real xacro.
    source = (PACKAGE / 'urdf/arm_control.urdf.xacro').read_text(encoding='utf-8')
    legacy = PACKAGE.parent / 'arm_control'
    source = source.replace('$(find arm_control)', legacy.as_posix())
    path = tmp_path / 'expanded_input.xacro'
    path.write_text(source, encoding='utf-8')
    xml = xacro.process_file(str(path)).toxml()
    root = ET.fromstring(xml)
    hardware = root.find('ros2_control')
    controller = yaml.safe_load((PACKAGE / 'config/controllers.yaml').read_text(encoding='utf-8'))
    joints = controller['arm_trajectory_controller']['ros__parameters']['joints']
    assert [j.attrib['name'] for j in hardware.findall('joint')] == joints
    assert {j.attrib['name'] for j in root.findall('joint')} == set(joints)
    assert hardware.find('hardware/plugin').text == 'linglong_control/SimSystem'
    assert hardware.find("hardware/param[@name='backend']").text == 'mock'
    for joint in hardware.findall('joint'):
        assert [i.attrib['name'] for i in joint.findall('command_interface')] == ['position']
        assert {i.attrib['name'] for i in joint.findall('state_interface')} == {'position', 'velocity'}
        physical = root.find(f"joint[@name='{joint.attrib['name']}']/limit")
        assert float(joint.find("param[@name='lower']").text) == float(physical.attrib['lower'])
        assert float(joint.find("param[@name='upper']").text) == float(physical.attrib['upper'])
        assert float(joint.find("param[@name='max_velocity']").text) == float(physical.attrib['velocity'])
    period = float(hardware.find("hardware/param[@name='nominal_period']").text)
    assert period * controller['controller_manager']['ros__parameters']['update_rate'] == 1
    assert len(hardware.find('sensor').findall('state_interface')) == 8
