"""Bark 推送实测：向你的 iPhone 发一条测试推送。

用法: scripts/test_bark.py <device_key 或完整推送URL>

device_key 在 Bark App 首页获取（形如 aBcD1234...，22 位左右）。
也可以直接粘贴 App 里给的完整 URL（https://api.day.app/<key>），脚本会自己解析。
"""
import json
import re
import sys
import urllib.request

SERVER = "https://api.day.app"


def parse_key(arg: str) -> str:
    m = re.search(r"api\.day\.app/([A-Za-z0-9]+)", arg)
    return m.group(1) if m else arg.strip().strip("/")


def push(key: str, title: str, body: str, server: str = SERVER) -> dict:
    payload = json.dumps({
        "device_key": key,
        "title": title,
        "body": body,
        "sound": "bell",
        "group": "盯盘",
    }).encode()
    req = urllib.request.Request(
        f"{server}/push", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    key = parse_key(sys.argv[1])
    r = push(key, "【盯盘】测试", "Bark 通道已打通：买入灯亮提醒将推送到这里。")
    print("响应:", json.dumps(r, ensure_ascii=False))
    if r.get("code") == 200:
        print("✅ 推送成功，检查手机通知（Bark App 需在后台允许通知）")
    else:
        print("❌ 推送失败，检查 device_key 是否正确")


if __name__ == "__main__":
    main()
