"""查询 通鼎互联(002491.SZ) 最近 5 个交易日的日 K 行情。

运行（项目根目录）:
    .venv/bin/python demo_kline.py

首次运行会自动从 TickFlow 回源并落库（data/），之后零网络请求。
"""
import time

from datacenter import DataCenter

dc = DataCenter()

end_ms = int(time.time() * 1000)
start_ms = end_ms - 15 * 86_400_000  # 往前多取 15 天，确保覆盖 5 个交易日

df = dc.get_klines("002491.SZ", period="1d", start_ms=start_ms, end_ms=end_ms)

recent = df.tail(5).copy()
recent["日期"] = recent["timestamp"].pipe(
    lambda s: __import__("pandas").to_datetime(s, unit="ms", utc=True)
    .dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d")
)
print(recent[["日期", "open", "high", "low", "close", "volume", "amount"]].to_string(index=False))
