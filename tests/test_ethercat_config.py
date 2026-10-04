import json

import pytest

import ethercat_config


def test_config_rejects_legacy_password(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(ethercat_config, "CONFIG_PATH", path)

    with pytest.raises(ValueError, match="不再支持保存 sudo 密码"):
        ethercat_config.save_config(
            {
                "mode": "ssh",
                "host": "192.168.1.201",
                "user": "enpht",
                "ssh_key": "key",
                "sudo_password": "do-not-log",
                "amplitude": 5000,
            }
        )
    assert path.exists() is False


def test_load_config_ignores_legacy_password_fields(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "mode": "ssh", "amplitude": 999999,
            "sudo_password": "plain", "sudo_password_encrypted": "plain:ZW5jb2RlZA==",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(ethercat_config, "CONFIG_PATH", path)

    config = ethercat_config.load_config()
    assert "sudo_password" not in config
    assert "sudo_password_encrypted" not in config
    assert "amplitude" not in config


def test_legacy_motion_settings_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(ethercat_config, "CONFIG_PATH", tmp_path / "config.json")
    saved = ethercat_config.save_config({"mode": "local", "amplitude": 999999})
    assert "amplitude" not in saved
