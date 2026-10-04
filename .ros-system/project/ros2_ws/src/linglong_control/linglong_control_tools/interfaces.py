"""Version 1: one left arm per ROS domain, root namespace, SI joint units.

Absolute endpoints are intentional. A node namespace alone does not relocate
this graph. Multi-arm namespaces require coordinated endpoints and TF prefixes.
"""
CONTRACT_VERSION = 1
JOINT_NAMES = ('joint_1', 'joint_2', 'joint_3', 'joint_5')
MANAGER = '/controller_manager'
TRAJECTORY_CONTROLLER = 'arm_trajectory_controller'
TRAJECTORY_ACTION = '/' + TRAJECTORY_CONTROLLER + '/follow_joint_trajectory'
CONTROLLER_STATE = '/' + TRAJECTORY_CONTROLLER + '/controller_state'
ACTION_STATUS = TRAJECTORY_ACTION + '/_action/status'
DYNAMIC_STATES = '/dynamic_joint_states'
DIAGNOSTICS = '/diagnostics'
DIAGNOSTIC_NAME = 'linglong/control'
BASE_FRAME = 'base_link'
TIP_FRAME = 'link_5'
