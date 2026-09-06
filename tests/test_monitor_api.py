# tests/test_monitor_api.py
from fastapi.testclient import TestClient
from webui.app import create_app


def _client(tmp_path):
    (tmp_path / "klines").mkdir()
    return TestClient(create_app(tmp_path))


def test_monitor_crud(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/monitor/tasks", json={
        "name": "t1", "symbol": "600869.SH",
        "script": 'def check(ctx):\n    return {"on": True}\n',
        "description": "原理+回放结果说明"})
    assert r.status_code == 200 and r.json()["id"] == 1
    items = c.get("/api/monitor/tasks").json()["items"]
    assert items[0]["symbol"] == "600869.SH" and items[0]["enabled"] == 1
    assert items[0]["lamp_on"] == 0 and "buy_on" not in items[0]
    assert items[0]["description"] == "原理+回放结果说明"
    r = c.put("/api/monitor/tasks/1", json={"interval_sec": 120,
                                            "description": "更新后的说明"})
    assert r.status_code == 200
    assert c.get("/api/monitor/tasks").json()["items"][0]["description"] == "更新后的说明"
    assert c.post("/api/monitor/tasks/1/toggle").json()["enabled"] == 0
    assert c.delete("/api/monitor/tasks/1").json()["ok"] is True
    assert c.get("/api/monitor/tasks").json()["items"] == []


def test_monitor_bad_script_400(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/monitor/tasks", json={
        "name": "bad", "symbol": "X", "script": "x = 1"})
    assert r.status_code == 400


def test_monitor_404(tmp_path):
    c = _client(tmp_path)
    assert c.put("/api/monitor/tasks/99", json={"name": "x"}).status_code == 404
