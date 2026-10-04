import can_control


def test_send_test_pulse_prefers_serial_bridge(monkeypatch):
    class DummyBridge:
        def __init__(self):
            self.calls = []

        def send_test_pulse(self, channel_name, amplitude=5, duration=0.5):
            self.calls.append((channel_name, amplitude, duration))
            return True, {'info': 'serial ok'}

    bridge = DummyBridge()
    monkeypatch.setattr(can_control, '_get_serial_bridge', lambda: bridge)

    ok, info = can_control.send_test_pulse('head', amplitude=3, duration=0.2)

    assert ok is True
    assert info['info'] == 'serial ok'
    assert bridge.calls == [('head', 3, 0.2)]


def test_send_test_pulse_fails_when_hardware_is_unavailable(monkeypatch):
    monkeypatch.delenv('LINGLONG_SIMULATION_MODE', raising=False)
    monkeypatch.setattr(can_control, '_try_hardware_send', lambda *_args, **_kwargs: (False, {'error': 'offline'}))

    ok, info = can_control.send_test_pulse('head')

    assert ok is False
    assert info['error'] == 'serial_send_failed'


def test_simulation_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv('LINGLONG_SIMULATION_MODE', 'true')
    monkeypatch.setattr(can_control, '_try_hardware_send', lambda *_args, **_kwargs: (False, {'error': 'offline'}))

    ok, info = can_control.send_test_pulse('head')

    assert ok is True
    assert info['simulated'] is True
