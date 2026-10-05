from unittest.mock import Mock
import pytest
from flask import Flask
import ros_control_bridge as bridge


def test_unconfigured_web_reports_unknown_and_never_falls_back(monkeypatch):
    monkeypatch.delenv('LINGLONG_ROS_URL', raising=False)
    result, status = bridge.call('trajectory', dict(offsets=[.01]*4, duration=6))
    assert status == 503 and not result['connected'] and result['state'] == 'UNKNOWN'


def test_remote_gateway_needs_token(monkeypatch):
    monkeypatch.setenv('LINGLONG_ROS_URL', 'http://192.0.2.1:8091')
    monkeypatch.delenv('LINGLONG_ROS_TOKEN', raising=False)
    assert bridge.call()[1] == 503


def test_web_auth_and_json_validation_before_transport(monkeypatch):
    app = Flask(__name__)
    bridge.register(app)
    transport = Mock(return_value=(dict(ok=True, accepted=True), 202))
    monkeypatch.setattr(bridge, 'call', transport)
    monkeypatch.setenv('LINGLONG_ADMIN_TOKEN', 'secret')
    client = app.test_client()
    assert client.post('/api/ros/enable', json={}).status_code == 403
    headers = {'X-Linglong-Admin-Token': 'secret'}
    assert client.post('/api/ros/enable', json={}, headers={**headers, 'Origin': 'http://other-site'}).status_code == 403
    assert client.post('/api/ros/enable', json=[], headers=headers).status_code == 400
    transport.assert_not_called()
    assert client.post('/api/ros/enable', json={}, headers=headers).status_code == 202
    transport.assert_called_once_with('enable', {})


def test_real_app_renders_control_page_and_blocks_direct_bus_tests(monkeypatch):
    import app as web
    monkeypatch.setenv('LINGLONG_ROS_URL', 'http://127.0.0.1:8091')
    monkeypatch.delenv('LINGLONG_ADMIN_TOKEN', raising=False)
    response = web.app.test_client().get('/ros-control')
    assert response.status_code == 200 and b'rosMotion' in response.data
    client = web.socketio.test_client(web.app)
    try:
        client.emit('run_controller_benchmark', {})
        result = next(e for e in client.get_received() if e['name'] == 'benchmark_result')
        assert not result['args'][0]['motion_allowed']
        client.emit('run_motor_preflight', {})
        result = next(e for e in client.get_received() if e['name'] == 'motor_preflight_result')
        assert not result['args'][0]['motion_allowed']
    finally:
        client.disconnect()
