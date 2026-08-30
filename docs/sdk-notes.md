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

## 2. 分钟K —— 当前账号无权限

`period="1m"`（无论是否带 start_time/end_time）抛出：

```
tickflow._exceptions.PermissionError: 无分钟K线查询权限
```

这是账号权限限制，非参数问题。start_time/end_time 参数名本身被 SDK 接受（错误发生在服务端鉴权阶段）。**后续任务若需要分钟K，需先升级账号权限；当前只能按日K设计。**

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
