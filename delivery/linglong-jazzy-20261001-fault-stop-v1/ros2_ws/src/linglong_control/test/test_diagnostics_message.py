"""Use actual ROS serialization: octet/int mismatches can abort a publisher."""
from types import SimpleNamespace as NS
import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.serialization import serialize_message, deserialize_message
from diagnostic_msgs.msg import DiagnosticArray
from linglong_control_tools.diagnostics import ControlDiagnostics


@pytest.mark.parametrize('level', [0, 1, 2, 3])
def test_diagnostics_levels_serialize_with_real_ros_types(level):
    messages = []
    node = NS(monitor=NS(status=lambda now: (level, 'test'), snapshot=None,
                        diagnostic_fields=lambda now: {'feedback_fresh': 'false'}),
              system_state=None, system_received=None,
              backend='mock', publisher=NS(publish=messages.append),
              get_clock=lambda: NS(now=lambda: rclpy.time.Time()))
    ControlDiagnostics.publish(node)
    decoded = deserialize_message(serialize_message(messages[0]), DiagnosticArray)
    value = decoded.status[0].level
    assert (value[0] if isinstance(value, bytes) else value) == level


def test_stale_diagnostics_never_export_old_active_as_current():
    from linglong_control_tools.health import HealthMonitor
    monitor = HealthMonitor()
    monitor.snapshot = {'control_health': {'active': 1., 'fault_code': 0., 'cycles': 15.}}
    monitor.last_received = monitor.last_progress = 1.
    fields = monitor.diagnostic_fields(2.)
    assert fields['feedback_fresh'] == 'false'
    assert 'active' not in fields and 'fault_code' not in fields
    assert fields['last_observed.active'] == '1.0'


def test_supervisor_fault_reason_survives_feedback_loss(monkeypatch):
    import linglong_control_tools.diagnostics as diagnostics
    from linglong_control_tools.health import HealthMonitor
    monkeypatch.setattr(diagnostics.time, 'monotonic', lambda: 10.)
    monitor = HealthMonitor()
    messages = []
    node = NS(monitor=monitor, backend='mock', publisher=NS(publish=messages.append),
              system_state={'state': 'FAULT', 'reason': 'hardware fault 5: control cycle timeout'},
              system_received=9.9, get_clock=lambda: NS(now=lambda: rclpy.time.Time()))
    ControlDiagnostics.publish(node)
    decoded = deserialize_message(serialize_message(messages[0]), DiagnosticArray)
    assert 'control cycle timeout' in decoded.status[0].message
    assert 'active' not in {v.key for v in decoded.status[0].values}

