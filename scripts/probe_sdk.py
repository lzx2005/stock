"""一次性探测脚本：确认 tickflow SDK 的真实行为（字段、异常、分页）。
运行: uv run python scripts/probe_sdk.py
"""
import time
from tickflow import TickFlow

tf = TickFlow()  # 读取环境变量 TICKFLOW_API_KEY

print("=== 1. 正常日K查询 ===")
df = tf.klines.get("600000.SH", period="1d", count=5, adjust="none", as_dataframe=True)
print(type(df), df.columns.tolist() if hasattr(df, "columns") else "")
print(df.dtypes)
print(df)

print("\n=== 2. 带时间范围的分钟K（验证 start_time/end_time 生效）===")
end_ms = int(time.time() * 1000)
start_ms = end_ms - 3 * 24 * 3600 * 1000
try:
    df2 = tf.klines.get("600000.SH", period="1m", start_time=start_ms, end_time=end_ms,
                        count=100, adjust="none", as_dataframe=True)
    print(f"rows={len(df2)}")
    if hasattr(df2, "columns") and len(df2):
        print("ts range:", df2["timestamp"].min(), "->", df2["timestamp"].max())
except Exception as e:
    print("分钟K查询失败! exception class:", type(e).__module__, type(e).__qualname__)
    print("str:", str(e)[:300])

print("\n=== 3. 非法 symbol 的行为 ===")
try:
    r = tf.klines.get("INVALID.XX", period="1d", count=5, as_dataframe=True)
    print("未抛异常! 返回:", type(r).__name__, f"shape={r.shape}" if hasattr(r, "shape") else repr(r)[:200])
except Exception as e:
    print("exception class:", type(e).__module__, type(e).__qualname__)
    print("args:", e.args)
    print("str:", str(e)[:300])

print("\n=== 4. 标的池 ===")
uni = tf.universes.get("CN_Equity_A")
print(type(uni), list(uni.keys()) if isinstance(uni, dict) else "")
symbols = uni["symbols"] if isinstance(uni, dict) else uni
print("A股标的数:", len(symbols), "示例:", symbols[:5])

print("\n=== 5. 限流信号探测（快速连发30次看是否报错）===")
errs = 0
for i in range(30):
    try:
        tf.klines.get("600000.SH", period="1d", count=1)
    except Exception as e:
        errs += 1
        print(f"  第{i+1}次触发异常: {type(e).__qualname__}: {str(e)[:200]}")
        break
print(f"完成, 异常数={errs}（0 说明 30 次连发未触限）")
