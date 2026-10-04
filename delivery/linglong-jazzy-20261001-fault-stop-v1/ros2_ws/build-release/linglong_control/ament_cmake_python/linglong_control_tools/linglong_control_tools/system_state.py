"""ROS-independent system policy. Hardware phases are hardware_state.hpp wire IDs.

The supervisor authorizes transitions; telemetry confirms their result. A fault
is latched, and a successful recovery never authorizes motion.
"""
from enum import IntEnum, Enum
from linglong_control_tools.health import FAULTS


class HardwareState(IntEnum):
    UNINITIALIZED = 0
    INIT = 1
    DISCOVERING = 2
    CONFIGURING = 3
    INACTIVE = 4
    ACTIVATING = 5
    ACTIVE = 6
    FAULT = 7
    RECOVERING = 8
    SHUTDOWN = 9


class SystemState(str, Enum):
    UNINITIALIZED = 'UNINITIALIZED'
    CONFIGURED = 'CONFIGURED'
    READY = 'READY'
    ENABLING = 'ENABLING'
    ENABLED = 'ENABLED'
    RUNNING = 'RUNNING'
    STOPPING = 'STOPPING'
    FAULT = 'FAULT'
    RECOVERING = 'RECOVERING'
    SHUTDOWN = 'SHUTDOWN'


class SystemStateMachine:
    def __init__(self, backend='mock'):
        if backend not in ('mock', 'ethercat_left_arm'):
            raise ValueError('unsupported backend')
        self.backend = backend
        self.state = SystemState.UNINITIALIZED
        self.reason = 'waiting for hardware and controllers'
        self.sequence = 0
        self.operation = None
        self.motion_authorized = False
        self.fault_reason = None
        self.ever_ready = False

    def transition(self, state, reason):
        if state != self.state:
            self.sequence += 1
        self.state, self.reason = state, reason

    def fail(self, reason):
        self.fault_reason = self.fault_reason or reason
        self.motion_authorized = False
        self.transition(SystemState.FAULT, self.fault_reason)

    def request(self, command):
        """Return an ordered service plan, or reject without side effects."""
        if self.operation:
            raise ValueError('another operation is in progress')
        if self.state == SystemState.SHUTDOWN:
            raise ValueError('shutdown is terminal; restart the launch')
        if command == 'enable':
            if self.state != SystemState.READY:
                raise ValueError('enable requires READY and fresh feedback')
            plan = [('hardware', 'active'), ('controller', 'active')]
            state = SystemState.ENABLING
        elif command == 'disable':
            if self.state not in (SystemState.ENABLED, SystemState.RUNNING, SystemState.READY):
                raise ValueError('disable requires READY, ENABLED or RUNNING')
            plan = [('controller', 'inactive'), ('hardware', 'inactive')]
            state = SystemState.STOPPING
        elif command == 'recover':
            if self.state != SystemState.FAULT:
                raise ValueError('recover requires a latched FAULT')
            if self.backend != 'mock':
                raise ValueError('physical fault recovery requires cause correction and process restart; '
                                 'automatic drive reset is not implemented')
            # Error handling can leave the ROS hardware UNCONFIGURED while the
            # plugin fault remains latched. MOCK on_configure explicitly resets
            # that fault if the framework has already skipped cleanup.
            plan = [('controller', 'inactive'), ('hardware', 'unconfigured'),
                    ('hardware', 'inactive'), ('broadcaster', 'active')]
            state = SystemState.RECOVERING
        elif command == 'shutdown':
            plan = [('controller', 'inactive'), ('hardware', 'finalized')]
            state = SystemState.STOPPING
        else:
            raise ValueError('unknown command')
        self.operation = command
        self.motion_authorized = False
        self.transition(state, f'{command} requested; awaiting confirmation')
        return plan

    def complete(self, success, reason=''):
        command, self.operation = self.operation, None
        if not success:
            self.fail(reason or f'{command} failed')
            return
        if command == 'shutdown':
            self.transition(SystemState.SHUTDOWN, 'hardware shutdown confirmed; not proof of mechanical stop')
        elif command == 'enable':
            self.motion_authorized = True
            self.transition(SystemState.CONFIGURED, 'enable services completed; awaiting fresh telemetry')
        else:
            if command == 'recover':
                self.fault_reason = None
            self.transition(SystemState.CONFIGURED, 'awaiting fresh inactive hardware feedback')

    def observe(self, hardware, controller, broadcaster, health, healthy, reason, moving=False):
        if self.state == SystemState.SHUTDOWN or self.operation:
            return
        if self.fault_reason:
            self.fail(self.fault_reason)
            return
        if health and (health.get('fault_code', 0) or health.get('hardware_state') == HardwareState.FAULT):
            code = int(health.get('fault_code', 0))
            self.fail(f"hardware fault {code}: {FAULTS.get(code, 'unknown')}")
            return
        if not healthy:
            if self.ever_ready or self.motion_authorized:
                self.fail(reason)
            else:
                self.transition(SystemState.UNINITIALIZED, reason)
            return
        phase = HardwareState(health['hardware_state'])
        if hardware == 'inactive' and phase == HardwareState.INACTIVE and controller == 'inactive' and \
                broadcaster == 'active' and not health['active'] and not health['commands_enabled']:
            if self.motion_authorized:
                self.fail('hardware/controller deactivated outside the supervisor')
                return
            self.ever_ready = True
            self.transition(SystemState.READY, 'feedback valid; drives disabled; explicit enable required')
        elif hardware == 'active' and phase == HardwareState.ACTIVE and controller == 'active' and \
                broadcaster == 'active' and health['active'] and health['commands_enabled']:
            if not self.motion_authorized:
                self.fail('hardware/controller enabled outside the supervisor')
                return
            self.transition(SystemState.RUNNING if moving else SystemState.ENABLED,
                            'trajectory goal in progress' if moving else 'enabled; no active trajectory goal')
        elif self.ever_ready or self.motion_authorized:
            self.fail('hardware, controller and command ownership states disagree')
        else:
            self.transition(SystemState.CONFIGURED, 'waiting for inactive hardware and configured controllers')
