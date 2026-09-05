"""探测 TickFlow SDK 的 WebSocket 能力（Task 1 spike）。

运行（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/probe_ws.py [symbol]

输出：连接/订阅 ack/收到的消息结构样例，写入 docs/sdk-notes.md §11。
"""
import json
import sys
import time

from tickflow import TickFlow

symbol = sys.argv[1] if len(sys.argv) > 1 else "600000.SH"
tf = TickFlow()

seen = []


def on_quotes(data):
    seen.append((time.time(), data))
    print(f"[{time.strftime('%H:%M:%S')}] quotes -> {len(data)} 条")
    if data:
        print(json.dumps(data[0], ensure_ascii=False, default=str)[:400])


def on_error(msg):
    print(f"[error] {msg}")


stream = tf.stream
stream.on_quotes(on_quotes)
stream.on_error(on_error)
stream.subscribe("quotes", [symbol])
stream.connect(block=False)

try:
    t0 = time.time()
    while time.time() - t0 < 12:
        time.sleep(1)
        print(f"  ... {time.time()-t0:.0f}s elapsed, {len(seen)} 批消息")
        if seen:
            break
finally:
    stream.close()

print(f"\n共收到 {len(seen)} 批消息")
if not seen:
    print("（休市或权限限制，无行情推送）")
