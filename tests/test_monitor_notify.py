# tests/test_monitor_notify.py
import json
import urllib.request
from unittest.mock import patch, MagicMock
from monitor import notify


def test_load_config_missing(tmp_path):
    assert notify.load_config(tmp_path / "none.json") == {}


def test_load_config_non_dict_json(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert notify.load_config(p) == {}


def test_send_no_key(tmp_path):
    assert notify.send("hi", config={}) is False


def test_send_success_payload(tmp_path):
    resp = MagicMock(); resp.read.return_value = b'{"code":200}'
    resp.__enter__ = lambda s: s; resp.__exit__ = lambda *a: None
    with patch.object(urllib.request, "urlopen", return_value=resp) as m:
        ok = notify.send("买入灯亮", config={"bark_key": "K1"})
    assert ok is True
    req = m.call_args[0][0]
    assert req.full_url == "https://api.day.app/push"
    body = json.loads(req.data)
    assert body["device_key"] == "K1" and body["body"] == "买入灯亮"
    assert body["group"] == "盯盘" and body["level"] == "timeSensitive"


def test_send_network_error_swallowed():
    with patch.object(urllib.request, "urlopen", side_effect=OSError("down")):
        assert notify.send("x", config={"bark_key": "K1"}) is False
