"""真实数据对拍：本地 apply_adjust(forward) vs 服务端 adjust="forward"。

运行（项目根目录，需 TICKFLOW_API_KEY）:
    source ~/.zshrc && .venv/bin/python scripts/verify_adjust.py [symbol] [days]

输出逐根最大误差，结论写入 docs/sdk-notes.md。误差 < 1e-6 即通过。
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from datacenter import DataCenter

DAY_MS = 86_400_000

symbol = sys.argv[1] if len(sys.argv) > 1 else "600000.SH"
days = int(sys.argv[2]) if len(sys.argv) > 2 else 800

with tempfile.TemporaryDirectory() as tmp:
    dc = DataCenter(data_dir=Path(tmp) / "data", rate_per_sec=100)
    end = int(pd.Timestamp.utcnow().timestamp() * 1000)
    start = end - days * DAY_MS

    # 本地：resolver 回填原始价 → apply_adjust 前复权（走完整缓存路径）
    local = dc.get_klines(symbol, "1d", start, end, adjust="forward")
    # 服务端直接前复权（穿透）
    remote = dc.client.get_klines_range(symbol, "1d", start, end, adjust="forward")

m = local[["timestamp", "close"]].merge(
    remote[["timestamp", "close"]], on="timestamp", suffixes=("_local", "_remote"))
err = (m["close_local"] - m["close_remote"]).abs().max()
print(f"{symbol}: {len(m)} 根可比, 最大绝对误差 {err:.2e}")
if m["close_remote"].abs().max() > 0:
    rel = ((m["close_local"] - m["close_remote"]).abs() / m["close_remote"]).max()
    print(f"最大相对误差 {rel:.2e}")
m["date"] = pd.to_datetime(m["timestamp"], unit="ms").dt.strftime("%Y-%m-%d")
print(m.tail(5).to_string(index=False))
print("PASS" if err < 1e-6 else "FAIL")
