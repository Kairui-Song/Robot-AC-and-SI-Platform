import pytest
from linglong_control_tools.system_state import HardwareState as H, SystemState as S, SystemStateMachine


def observe(machine, enabled=False, moving=False, **changes):
    health = dict(hardware_state=H.ACTIVE if enabled else H.INACTIVE,
                  fault_code=0, active=int(enabled), commands_enabled=int(enabled))
    health.update(changes)
    machine.observe('active' if enabled else 'inactive', 'active' if enabled else 'inactive',
                    'active', health, True, 'healthy', moving)


def ready(backend='mock'):
    machine = SystemStateMachine(backend)
    observe(machine)
    assert machine.state == S.READY
    return machine


def test_enable_running_completion_and_disable():
    m = ready()
    assert m.request('enable') == [('hardware', 'active'), ('controller', 'active')]
    assert m.state == S.ENABLING
    m.complete(True)
    observe(m, enabled=True)
    assert m.state == S.ENABLED
    observe(m, enabled=True, moving=True)
    assert m.state == S.RUNNING
    observe(m, enabled=True)
    assert m.state == S.ENABLED
    assert m.request('disable') == [('controller', 'inactive'), ('hardware', 'inactive')]
    m.complete(True)
    observe(m)
    assert m.state == S.READY and not m.motion_authorized


def test_fault_cannot_be_cleared_by_good_telemetry_or_enable():
    m = ready()
    observe(m, hardware_state=H.FAULT, fault_code=6)
    observe(m)
    assert m.state == S.FAULT
    with pytest.raises(ValueError):
        m.request('enable')
    m.request('recover')
    assert m.state == S.RECOVERING
    m.complete(True)
    observe(m)
    assert m.state == S.READY and not m.motion_authorized


def test_physical_recovery_is_explicitly_rejected_without_changes():
    m = ready('ethercat_left_arm')
    m.fail('bus unavailable')
    with pytest.raises(ValueError, match='process restart'):
        m.request('recover')
    assert m.state == S.FAULT and m.operation is None


@pytest.mark.parametrize('command', ['enable', 'recover', 'disable'])
def test_uninitialized_requests_rejected(command):
    with pytest.raises(ValueError):
        SystemStateMachine().request(command)


def test_parallel_requests_and_terminal_shutdown():
    m = ready()
    m.request('enable')
    with pytest.raises(ValueError, match='in progress'):
        m.request('shutdown')
    m.complete(False, 'switch failed')
    assert m.state == S.FAULT
    m.request('shutdown')
    m.complete(True)
    observe(m)
    assert m.state == S.SHUTDOWN
    with pytest.raises(ValueError, match='terminal'):
        m.request('enable')


def test_stale_stream_and_external_enable_latch_fault():
    m = ready()
    m.observe(None, None, None, None, False, 'stale')
    assert m.state == S.FAULT and m.reason == 'stale'
    m = ready()
    observe(m, enabled=True)
    assert m.state == S.FAULT and not m.motion_authorized


def test_ownership_mismatch_and_failed_recovery_remain_faulted():
    m = ready()
    m.request('enable')
    m.complete(True)
    observe(m, enabled=True, commands_enabled=0)
    assert m.state == S.FAULT
    m.request('recover')
    m.complete(False, 'feedback unavailable')
    assert m.state == S.FAULT


def test_repeated_observation_does_not_increment_transition_counter():
    m = ready()
    sequence = m.sequence
    observe(m)
    assert m.sequence == sequence
