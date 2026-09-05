# TickFlow SDK 探测笔记

探测日期：2026-08-30
SDK 版本：tickflow 0.1.25（`tickflow[all]>=0.1.17` 解析得到）
探测脚本：`scripts/probe_sdk.py`（`source ~/.zshrc && uv run python scripts/probe_sdk.py`）
环境：pandas 3.0.5、Python 3.14

## 1. 日K 返回结构（`tf.klines.get`）

真实调用签名（与官方文档一致，参数名已验证可用）：

```python
tf.klines.get(symbol, period="1d", count=5, adjust="none", as_dataframe=True)
# 也接受 start_time/end_time（毫秒时间戳）
```

`as_dataframe=True` 返回 `pandas.DataFrame`，11 列，dtype 如下：

| 列名 | dtype | 说明 |
|---|---|---|
| symbol | str | 如 `600000.SH` |
| name | str | 如 `浦发银行` |
| timestamp | int64 | 毫秒时间戳，如 `1787500800000` |
| trade_date | str | 如 `2026-08-24` |
| trade_time | str | 日K为空字符串 |
| open | float64 | |
| high | float64 | |
| low | float64 | |
| close | float64 | |
| volume | int64 | |
| amount | float64 | |

注意：pandas 3.0 下字符串列 dtype 为 `str`（不是旧的 `object`）。

`as_dataframe=False`（默认）返回 `dict`，**只有 7 个键**：`timestamp, open, high, low, close, volume, amount`（无 symbol/name/trade_date/trade_time），值为 list。

## 2. 分钟K —— 已开通（2026-08-30 更新），深度限最近一年

`period="1m/5m/15m/30m/60m"` 均返回真实数据，**历史深度限最近一年**（更早区间返回空或 400）。

早前（旧套餐）`period="1m"` 曾抛 `PermissionError: 无分钟K线查询权限`——该限制已随套餐升级解除，现为深度限制而非权限。当前账号权限状态汇总：
- 分钟K：✅ 可用（限 1 年深度）
- 日K 及以上：✅ 可用（限流 60 次/分，见 §8）
- 当日 intraday 分钟K：✅ 可用（§11.5 真实验证）
- WS 实时推送：❌ 无权限（§11）
- 财务数据：❌ 无权限（§10.5）

因此历史分钟回填只覆盖最近一年（见 phase4 Task 6 实测）。

## 3. 非法 symbol —— 不抛异常

`tf.klines.get("INVALID.XX", period="1d", count=5)` **不抛异常**，返回空数据：

- `as_dataframe=False`：`{'timestamp': [], 'open': [], ...}`（7 个键的空 list）
- `as_dataframe=True`：空 DataFrame（shape=(0, 11)，列结构完整）

**对后续任务的影响**：`TickFlowClient` 不能用 try/except 判断 symbol 无效，必须检查返回行数为 0。

## 4. 标的池（`tf.universes.get("CN_Equity_A")`）

返回 `dict`，键：`id, name, description, region, category, symbol_count, symbols`。

- A股标的数：**5555**
- 示例：`['000001.SZ', '000002.SZ', '000006.SZ', '000007.SZ', '000008.SZ']`

## 5. 限流

快速连发日K请求，第 7~9 次触发：

```
tickflow._exceptions.RateLimitError: 请求频率超限 (10/min)，请 38578ms 后重试
```

- 限流阈值：**10 次/分钟**（远低于预期，批量抓取必须内置节流 + 重试）
- 异常 message 中包含建议等待毫秒数，但结构化字段里没有 retry_after，需要从 str 解析或按固定退避处理

## 6. 异常类层次（`tickflow._exceptions`，供 `classify_error` 使用）

```
TickFlowError(Exception)
├── APIError(TickFlowError)          # 带 code:str, status_code:int, details:Optional[Any]
│   ├── AuthenticationError
│   ├── BadRequestError
│   ├── InternalServerError
│   ├── NotFoundError
│   ├── PermissionError              # 分钟K权限命中此类
│   └── RateLimitError               # 限流命中此类（HTTP 429）
├── ConnectionError(TickFlowError)   # 注意：非内置 ConnectionError，需用全限定名区分
└── TimeoutError(TickFlowError)      # 同上，非内置 TimeoutError
```

`APIError.__init__(self, message: str, *, code: str, status_code: int, details: Optional[Any] = None)`

注意：`tickflow._exceptions.PermissionError/ConnectionError/TimeoutError` 会遮蔽内置同名类，导入时务必用模块前缀（`from tickflow import _exceptions` 或 `import tickflow._exceptions as tf_exc`）。

## 7. 环境备注

- `TICKFLOW_API_KEY` 配置在 `~/.zshrc`，非交互 shell 需先 `source ~/.zshrc`（或使用 `zsh -ic`）才能继承。
- 首次 `uv sync` 直连 PyPI 极慢（~100KB/s），改用清华镜像后秒级完成：`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync`。

## 8. 新套餐实测（2026-08-30，Task 3 Step 0，脚本 `scripts/probe_task3.py`）

### 8a. 限流：新套餐明显放宽

以约 1 次/秒的间隔连发 25 次 `tf.klines.get("600000.SH", period="1d", count=1)`，**0 次 RateLimitError**。
说明新套餐日K限流至少 60 次/分钟（官方规格：日线按只 120次/分、批量 60次/分×200标的；分钟按只 60次/分、批量 30次/分×100标的）。第 5 节记录的 10次/分钟为旧套餐实测，已过时。客户端默认限速仍建议保守（如 10/s 以内），配合 429 重试兜底。

### 8b. `klines.batch` 返回结构（as_dataframe=True）

```python
tf.klines.batch(["600000.SH", "000001.SZ"], period="1d", count=5, adjust="none", as_dataframe=True)
```

- 返回 **`dict[symbol, pandas.DataFrame]`**，每个 DataFrame 与 `klines.get(as_dataframe=True)` 同构（11 列，含 symbol/name/trade_date/trade_time）。
- `count` **按标的计**：count=3 → 每个标的各 3 行。
- 非法 symbol **不抛异常**，该 key 直接从 dict 中缺失（`batch(["INVALID.XX"], ...)` 返回 `{}`）。
- 签名还接受 `start_time/end_time`（毫秒）、`show_progress`、`max_workers`、`batch_size`（默认 100，SDK 内部分块并发）。

## 9. ex_factors 与复权语义校准（2026-08-30，`scripts/calibrate_adjust.py`）

### 调用形态

`tf.klines.ex_factors("600000.SH")` 返回 **`dict`**：`{symbol: [{timestamp, ex_factor}, ...]}`（timestamp 毫秒）。

### 因子语义（真实对拍，最大误差 0）

取 600000.SH 800 根日线，`adjust="none"` 与 `adjust="forward"` 对拍，`ratio = close_fwd / close_raw`：

- 最新交易日 `ratio = 1.0`（**前复权基准 = 最新价**，符合预期）
- 最佳拟合：`ratio(t) = ∏_{ex_date_i > t} (1 / factor_i)`，误差精确为 0
- **结论**：前复权 = 除权日**之前**的历史 bar 价格 **× (1/factor)**，对后续所有因子累积
- 真实因子均为 **> 1**（如 1.0065、1.5169，即除权日价格回落比例）；**与 phase2 计划 Task 2 假设「因子<1、乘」相反**，实现时翻转

### 对 `adjust.py` 的影响

```python
for ex_ts, factor in sorted(factors):
    if adjust == "forward":
        cum[ts < ex_ts]  *= 1.0 / factor   # 历史价除以因子（校准结果）
    else:  # backward
        cum[ts >= ex_ts] *= factor          # 后复权取倒数
volume = volume / cum  # 保持 amount ≈ price × volume；amount 不动
```

## 10.5 财务数据 —— 当前账号无权限（2026-08-30）

`tf.financials.metrics(["600519.SH", "000001.SZ"], ...)` 抛出：

```
tickflow._exceptions.PermissionError: 无公司财务数据查询权限
```

与分钟K（§2）同类账号限制。**Task 4 的 FinancialStore/客户端/门面均已按 fake 实现并通过 3 单测，
真实回源 smoke 因权限被阻塞**，待账号升级后执行 `scripts/verify_financials.py`（或直接：
`dc.get_financials("metrics", ["600519.SH", "000001.SZ"])` 首次回源、二次走缓存）验证字段。

## 11. WebSocket 实时行情（2026-08-30，`scripts/probe_ws.py`）

### SDK 能力（已确认存在，非未知数）

- `tf.stream`（`MarketStream`）：统一 WS 流，channel `quotes`/`depth`
- 端点：`wss://<base>/v1/ws/stream?api_key=<key>`（**鉴权走 URL query**）
- 订阅协议：`{"op": "subscribe", "channel": ch, "symbols": [...]}`；服务端回 `subscribed` ack / `error`
- 推送：`{"op": "quotes", "data": [ {...quote}, ... ]}` / `{"op": "depth", "data": [...]}`
- SDK 内置 `websockets` 连接 + 断线自动重连 + 重连后自动重订阅（ping 20s）
- 另有 `tf.realtime`（`QuoteStream`，仅 quotes）、`AsyncMarketStream`/`AsyncQuoteStream`（async 版）

### 账号权限（2026-08-30 实测）

```
WS connection rejected (HTTP 403): NO_WS_PERMISSION: 当前套餐不支持 WebSocket，需购买 WebSocket 实时行情功能
```

**当前套餐无 WS 权限**（HTTP 403，`on_error` 收到 `NO_WS_PERMISSION`）。与分钟K（§2）、财务（§10.5）同类账号限制。
代码层全部可按文档实现（Task 4 用 `tf.stream` + `on_quotes`），真实盘中运行需升级套餐开通 WS。

### 盘中 REST intraday —— 有权限 ✅

```python
df = tf.klines.intraday("600000.SH", as_dataframe=True)   # 当日 1m，08-28 返回 241 根
```

**注意**：`klines.intraday`（当日分钟K）**有权限**，而 `klines.get(period="1m")` 报「无分钟K线查询权限」。
Task 5 半可变层可用 intraday 真实验证；日终分钟线固化（Task 6）若走 `klines.get(period="1m")` 仍被拦，
历史分钟数据回填不可行，只能依赖 intraday 固话当日。

## 10. get_klines 集成复权真实对拍（2026-08-30，`scripts/verify_adjust.py`）

本地路径（resolver 回填原始价 → `apply_adjust`）vs 服务端 `adjust="forward"` 直接查询，600000.SH 近 800 天：

```
600000.SH: 532 根可比, 最大绝对误差 1.78e-15, 最大相对误差 2.16e-16
```

远小于 1e-6，本地复权与服务端完全一致。`DataCenter.get_klines(..., adjust=...)` 默认 `"forward"`；
`"none"` 返回缓存原始价；`"forward_additive"/"backward_additive"` 本地不实现，穿透回源（不读缓存、不回填）。

### 11.5 盘中半可变层当日段真实验证（2026-08-30，Task 5）

`dc.get_klines(symbol, "1m", today_start, now)` 当日段走 `tf.klines.intraday`（有权限），
周末休市返回 0 行、无异常；TTL 缓存二次查询不重复打接口；`kline_coverage` 保持 None 不被当日污染。
（历史 1m 段当时被 §2 的权限问题阻塞；**权限现已开通**，历史分钟回填可走 `klines.get`，深度限最近一年。）

> 2026-08-30 phase4 Task 5 还发现：`get_klines("1d")` 跨今日零点时误调 `get_intraday("1d")`（接口只支持分钟周期），
> 已改为聚合当日 1m intraday 成一根日线 bar（时间戳=北京当日 0 点），加回归测试。
