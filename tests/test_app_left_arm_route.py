import app as web_app
import ethercat_config
def test_single_legacy_motion_request_is_rejected():
    client = web_app.socketio.test_client(web_app.app)
    client.emit("run_test", {"target": "left_arm"})

    result = next(item for item in client.get_received() if item["name"] == "test_result")
    assert result["args"][0] == {
        "target": "left_arm",
        "ok": False,
        "reason": "legacy_motion_disabled",
        "error": "历史运动测试接口已由服务端禁用。",
    }


def test_config_write_requires_token_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv('LINGLONG_ADMIN_TOKEN', 'test-token')
    monkeypatch.setattr(ethercat_config, 'CONFIG_PATH', tmp_path / 'config.json')
    client = web_app.app.test_client()

    response = client.post('/api/ethercat-config', json={'mode': 'local'})

    assert response.status_code == 403
    assert response.get_json()['ok'] is False


def test_legacy_batch_motion_request_is_rejected():
    client = web_app.socketio.test_client(web_app.app)
    client.emit("run_batch", {"targets": ["left_arm"]})

    result = next(item for item in client.get_received() if item["name"] == "batch_report")
    assert result["args"][0] == {
        "ok": False,
        "reason": "legacy_motion_disabled",
        "error": "历史批量运动测试接口已由服务端禁用。",
    }
