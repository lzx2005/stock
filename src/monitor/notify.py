"""Bark 推送通知：盯盘信号推送到 iPhone。

配置存放在 data/monitor_config.json：

    {"bark_key": "<device_key>", "bark_server": "https://api.day.app"}

- bark_server 可选，默认 https://api.day.app（自建 Bark 服务器时覆盖）。
- 任何配置缺失、网络/HTTP 异常都不抛异常，只返回 False——监控主循环不能因推送失败中断。
"""
import json
import urllib.request
from pathlib import Path

DEFAULT_SERVER = "https://api.day.app"
DEFAULT_CONFIG_PATH = "data/monitor_config.json"


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict:
    """加载推送配置；文件不存在、JSON 损坏或顶层非 dict 时返回 {}。"""
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


def send(text: str, config: dict | None = None,
         config_path: str | Path = DEFAULT_CONFIG_PATH) -> bool:
    """发送 Bark 推送，成功返回 True。

    config=None 时从 config_path 加载。无 bark_key、网络/HTTP 异常、
    服务端返回 code!=200 均返回 False（不抛异常）。
    """
    if config is None:
        config = load_config(config_path)
    key = config.get("bark_key")
    if not key:
        return False
    server = config.get("bark_server") or DEFAULT_SERVER
    payload = json.dumps({
        "device_key": key,
        "title": "盯盘信号",
        "body": text,
        "group": "盯盘",
        "sound": "bell",
        "level": "timeSensitive",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/push", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("code") == 200
    except Exception:
        return False
