"""Task 3 Step 0 探测：新套餐限流 + klines.batch 返回结构。"""
import time

import pandas as pd
from tickflow import TickFlow

tf = TickFlow()

print("=== 0a. 新套餐限流实测：1次/秒 连发 25 次日线请求 ===")
errors = 0
for i in range(25):
    t0 = time.monotonic()
    try:
        df = tf.klines.get("600000.SH", period="1d", count=1, as_dataframe=True)
        print(f"#{i+1:02d} ok rows={len(df)}")
    except Exception as e:
        errors += 1
        print(f"#{i+1:02d} ERROR {type(e).__module__}.{type(e).__name__}: {e}")
    dt = time.monotonic() - t0
    if dt < 1.0:
        time.sleep(1.0 - dt)
print(f"done, errors={errors}")

print()
print("=== 0b. klines.batch 返回结构 ===")
res = tf.klines.batch(["600000.SH", "000001.SZ"], period="1d", count=5,
                      adjust="none", as_dataframe=True)
print("type:", type(res))
if isinstance(res, dict):
    for k, v in res.items():
        print(f"  key={k!r} value type={type(v).__name__}", end="")
        if isinstance(v, pd.DataFrame):
            print(f" shape={v.shape} cols={list(v.columns)}")
            print(v.head(3).to_string())
        else:
            print(f" value={v!r}")
elif isinstance(res, pd.DataFrame):
    print("shape:", res.shape)
    print("cols:", list(res.columns))
    print(res.head(10).to_string())

print()
print("--- 空结果形态：非法 symbol ---")
res2 = tf.klines.batch(["INVALID.XX"], period="1d", count=5,
                       adjust="none", as_dataframe=True)
print("type:", type(res2))
if isinstance(res2, dict):
    for k, v in res2.items():
        print(f"  key={k!r} type={type(v).__name__}", end="")
        print(f" shape={v.shape}" if isinstance(v, pd.DataFrame) else f" value={v!r}")
elif isinstance(res2, pd.DataFrame):
    print("shape:", res2.shape, "cols:", list(res2.columns))

print()
print("--- count 语义：count=3 每标的返回几行？ ---")
res3 = tf.klines.batch(["600000.SH", "000001.SZ"], period="1d", count=3,
                       adjust="none", as_dataframe=True)
if isinstance(res3, dict):
    for k, v in res3.items():
        print(f"  {k}: {len(v)} rows" if isinstance(v, pd.DataFrame) else f"  {k}: {v!r}")
elif isinstance(res3, pd.DataFrame):
    print(res3.groupby("symbol").size() if "symbol" in res3.columns else res3.shape)
