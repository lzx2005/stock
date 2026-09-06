---
name: monitor-expert
description: 盯盘专家——把用户的自然语言盯盘需求变成 check(ctx) 脚本，验证后注册进日内盯盘系统并负责诊断。当用户提出"帮我盯某只股票/某标的"、"价格到 XX 时提醒我"、"盯一下 XX 的金叉/低位区/止损"、"XX 条件满足了通知我"、"监控我的自选股"、"为什么没收到提醒"等需求时，务必使用本 skill（即使用户没有明说"盯盘"两个字，只要是在本仓库语境下要求行情触发提醒/买卖信号通知/监控某条件，都应触发）。它能生成盯盘脚本、跑三段验证（语法/干跑/历史回放）、注册与启停任务、排查"没提醒"问题。
---

# 盯盘专家

## 你的职责

用本仓库的**日内盯盘系统**（`src/monitor/`），把用户的盯盘需求做成常驻任务，交付四件事（spec §13）：

1. **生成**：自然语言 → `check(ctx)` 脚本。澄清条件里的话术（"低位区"= 近 20 日最低价上方 2%？还是 60 日价格分位数 <20%？——给出默认并在注册时写明口径）；优先用因子库（`ctx.factor`）而非手搓指标；脚本无副作用、无状态、每次轮询独立。
2. **验证（注册前必做）**：① `compile()` 语法检查；② 用真实 DataCenter 构造 ctx **干跑一次**确认不抛异常、返回结构合法（on 为 bool/None）；③ **历史触发回放**：用近 N 天日线把同一条件逐日评估，报告"过去 3 年会触发约 X 次、最近三次触发日期"——让用户判断条件太松还是太严（这是金融专家的核心价值，防止注册一个每分钟都亮灯或永远不响的废条件）。
3. **注册/管理**：通过 `scripts/monitor_cli.py` 注册任务（写入 monitor.db）、启停、查看任务列表与灯状态。
4. **诊断**：用户问"为什么没提醒"时，查任务的 `last_error`/`error_count`/`poll_count`、信号历史，结合脚本逻辑给出解释（条件没满足 / 脚本报错 / 停牌无数据 / 非交易时段 / notify 关了 / 推送失败）。

## 边界

- 只生成/验证/注册脚本，**不改盯盘系统本身**（`src/monitor/` 的代码出了问题让用户决定，不顺手改）。
- **拒绝任何下单/交易动作请求**——本系统是纯提醒系统，信号由用户手动去同花顺执行。
- 脚本无状态、每次轮询独立调用；需要跨轮状态的需求不支持（YAGNI），向用户说明。
- 标的范围是固定自选股池（一个任务一个标的）；不做全市场扫描（限流不允许）。

## 工作流程

### Step 1 · 澄清口径

把用户话术转成严谨的条件定义。**缺参数时用合理默认，并在注册时把口径写进任务名称/告知用户**（如"低位区"默认 = 近 20 日最低价上方 2% 以内）。优先用因子库内置因子，其次用 `ctx.daily(n)` 自己算。时段类条件（如"尾盘"）用 `ctx.minute_bars()` 最后一根时间戳判断（见下方示例 5）。

### Step 2 · 生成脚本

写一个只含 `check(ctx)` 的 Python 文件（临时放项目根 scratch 位置，如 `reports/` 下）。参照下方"示例脚本库"改写，不要自由发挥数据结构。脚本里**不要自己写"只提醒一次"逻辑**——亮灭灯/边沿去重是 daemon 的活，脚本只需返回条件当前是否成立。

### Step 3 · 三段验证（注册前必做）

```bash
source ~/.zshrc   # 必须：非交互 shell 拿不到 TICKFLOW_API_KEY，干跑/回放回源会失败
.venv/bin/python scripts/validate_watch.py <script.py> <symbol> [--days 750]
```

输出三段：

1. **语法 OK**——compile 检查；
2. **干跑返回值**——真实 DataCenter 构造当前 ctx 跑一次，打印 `on=/msg=`；
3. **回放触发次数 + 最近 3 次触发日期**——近 N 个自然日逐交易日评估同一条件。

**把回放次数给用户判断松紧**：3 年触发几百次 = 太松（会亮成常灯），0 次 = 太严（永远不响），据此调阈值后重新验证。

### Step 4 · 注册

```bash
.venv/bin/python scripts/monitor_cli.py register --name "600869 20日低位区" \
    --symbol 600869.SH [--interval 60] [--no-notify] --script-file <script.py> \
    --description "原理：…实现：…回放：近N年触发X次/最近三次日期…"
# → 打印 task_id=，把 task_id 告知用户
```

**`--description` 必填**（webui 任务列表悬停可见全文、抽屉可编辑）：三段式写清 ① 盯盘原理（条件口径，含你选的默认值）② 实现方式（用了 ctx 哪个方法/哪个因子、关键阈值）③ 回放结果（近 N 年触发次数/边沿频率/最近触发日期，从 Step 3 验证输出抄）。

管理：`monitor_cli.py list`（任务列表含灯状态/错误）、`show <id>`（详情+脚本全文）、`toggle <id>`（启停翻转）、`delete <id> --yes`。

注册后告知用户：**灯语义**——一个任务一盏信号灯，条件成立 = 灯亮（代表"指标生效"，是买是卖由任务含义决定，写进任务名称/说明）。条件首次满足（False→True）亮灯并推送一次；之后页面持续亮灯；条件不再满足（True→False）灭灯并推送一次。**提醒只发生在灯的亮/灭边沿**，条件持续成立期间不会反复推送。

## MonitorContext 契约（spec §6）

脚本只定义一个 `check(ctx)` 函数（需要 import 时允许在 script 顶部自行 import，如 numpy/pandas），返回 dict。ctx 由 daemon 用任务行的 `symbol` 构造，**方法均不带 symbol 参数**：

| 方法 | 返回 | 实现 |
|---|---|---|
| `ctx.price()` | float 最新价 | 当日 1m 最后一根 close |
| `ctx.minute_bars()` | 当日 1m DataFrame | `dc.get_klines(symbol, "1m", today, now)`（intraday 半可变层，TTL 缓存） |
| `ctx.daily(n)` | 近 n 根日线 DataFrame | 历史日线 + 今日未完成日K（1m 聚合，复用现有 intraday 合成逻辑） |
| `ctx.factor(name, params, n)` | 因子 Series（按 timestamp 索引，n=取数窗口根数，须带够 lookback） | FactorStore（`import factors.factors` 由 runtime 统一做） |

**返回值约定**：`on` 为 `True/False/None`——`None` 表示本轮不判断（灯状态不变、不通知）；`msg` 字符串随信号入库。脚本必须**无副作用、无状态**（每次轮询独立调用）。pandas 比较产生的 numpy 布尔会被 runtime 自动归一为 Python bool，但写 `bool(...)` 包一层更稳妥。

**执行方式**：`exec(script, namespace)` 取 `namespace["check"]`；加载失败（语法错/无 check）记 `last_error`，任务不执行。本地纯自用，不做沙箱。

**脚本里不要自己写"只提醒一次"逻辑**——边沿去重（亮灯只推一次、灭灯只推一次）由 daemon 根据 DB 灯状态判定；脚本只报告"条件此刻是否成立"。

## 数据/因子调用速查（spec §13.1）

**脚本内（盯盘脚本只允许走 ctx，不直接 import DataCenter）**：

```python
ctx.price()                  # float，当日最后 1m bar 收盘价
ctx.minute_bars()            # 当日 1m DataFrame[timestamp,open,high,low,close,volume,amount]
ctx.daily(n)                 # 近 n 根日线 DataFrame，含今日实时合成日K（最后一根是"现在"）
ctx.factor("ma", {"n": 20}, 120)   # FactorStore 取因子 Series（按 timestamp 索引），
                             # 第三参是取数窗口（根数）；因子须带够 lookback
```

**skill 侧（验证/回放/诊断时可直接用模块，脚本不行）**：

```python
import factors.factors            # 必须，显式注册内置因子
from datacenter import DataCenter
from factors import FactorStore

dc = DataCenter()
df = dc.get_klines("600869.SH", "1d", start_ms, end_ms, adjust="forward")  # 缓存优先
fs = FactorStore(dc)
ma20 = fs.get("600869.SH", "ma", {"n": 20}, "1d", start_ms, end_ms)        # Series
```

内置因子（参数/语义以 `src/factors/factors.py` doc 为准）：`ma/ema/rsi/atr/macd_hist/kdj_j/boll_up/boll_low/vol_ratio/mom/bias`。盯盘任务的启用/灯状态/信号历史直接读 `monitor.db`（经 `monitor.store`，不要手写 SQL）。

## 示例脚本库（spec §13.2，生成时参照改写）

**例 1 · 20 日低位区（震荡市低吸，用户原话场景）**

```python
def check(ctx):
    px = ctx.price()
    hist = ctx.daily(60)
    low20 = hist["low"].tail(20).min()
    in_zone = px <= low20 * 1.02          # 近20日最低价上方 2% 以内
    return {"on": in_zone,
            "msg": f"现价{px:.2f} 20日低点{low20:.2f}"}
```

**例 2 · 回踩 MA20 不破（趋势票持股线，对应周五研究结论"线上持股线下不碰"）**

```python
def check(ctx):
    px = ctx.price()
    ma20 = ctx.factor("ma", {"n": 20}, 60).iloc[-1]
    near = abs(px - ma20) / ma20 <= 0.01   # 距 MA20 1% 以内
    above = px >= ma20                      # 且没跌破
    return {"on": near and above,
            "msg": f"现价{px:.2f} MA20={ma20:.2f}"}
```

**例 3 · 放量突破 20 日新高（动量跟进）**

```python
def check(ctx):
    d = ctx.daily(30)
    px = ctx.price()
    high20 = d["high"].iloc[-21:-1].max()  # 前 20 日最高（不含今日）
    vr = ctx.factor("vol_ratio", {"n": 5}, 30).iloc[-1]
    breakout = px > high20 and vr > 1.5
    return {"on": breakout,
            "msg": f"现价{px:.2f} 前20日高{high20:.2f} 量比{vr:.2f}"}
```

**例 4 · 盘中金叉预警（MA5 上穿 MA20，今日用实时合成日K）**

```python
def check(ctx):
    d = ctx.daily(30)
    closes = d["close"]                     # 最后一根=今日实时价
    ma5 = closes.rolling(5).mean()
    ma20 = closes.rolling(20).mean()
    cross = ma5.iloc[-2] <= ma20.iloc[-2] and ma5.iloc[-1] > ma20.iloc[-1]
    return {"on": bool(cross),
            "msg": f"MA5={ma5.iloc[-1]:.2f} MA20={ma20.iloc[-1]:.2f}"}
```

**例 5 · 尾盘跳水避险灯（14:30 后当日跌幅超 1% 亮灯，周五研究的应用）**

```python
def check(ctx):
    bars = ctx.minute_bars()
    if bars.empty:
        return {"on": None, "msg": "无当日数据"}
    last_ts = bars["timestamp"].iloc[-1]
    hhmm = (last_ts // 1000 % 86400 + 8 * 3600) // 60  # 北京时间分钟数
    if hhmm < 14 * 60 + 30:
        return {"on": False, "msg": "未到尾盘"}
    d = ctx.daily(2)
    prev_close = d["close"].iloc[-2]         # 昨收（倒数第二根=昨天）
    drop = ctx.price() / prev_close - 1
    return {"on": drop <= -0.01,
            "msg": f"尾盘当日跌幅{drop:+.2%}"}
```

**例 6 · 成本止损灯（用户报成本价，AI 写死进脚本——脚本无状态，成本由用户提供）**

```python
COST = 12.30   # 用户持仓成本，注册时由用户告知

def check(ctx):
    px = ctx.price()
    atr = ctx.factor("atr", {"n": 14}, 30).iloc[-1]
    stop = COST - 2 * atr
    return {"on": px < stop,
            "msg": f"现价{px:.2f} 止损线{stop:.2f}(成本{COST}-2ATR)"}
```

## 数据约束防坑

- **WS 无权限**：TickFlow 当前套餐无 WebSocket 推送（`NO_WS_PERMISSION`），实时数据走 **REST 轮询当日 1m**——信号时效就是 1 分钟级，别承诺更快。
- **分钟K 深度 1 年**：历史分钟K 只有最近一年；盯盘只用当日分钟 + 历史日线，不受影响。回放里 `price()` 有日线兜底（分钟为空时取当日日K 收盘），日线口径的条件全时段可回放；**只有依赖分钟线细节的脚本**（如例 5 用 `minute_bars()` 最后一根时间戳判断 14:30）在超过 1 年的日期拿不到分钟数据——`minute_bars()` 返回空 df，脚本按"无当日数据"分支走，回放结果对这些日期不代表真实盘中行为，解读时说明。
- **限流**：分钟按只 60 次/分、批量 30 次/分×100 标的。单任务 interval 最小 60s，别建议更小；也别注册一大堆高频任务。
- **停牌日无 bar**：ctx 取数为空 → daemon 静默跳过本轮，不报错，属正常。
- **休市 intraday 返回空**：周末/节假日任务空转不报错；`daily(n)` 最后一根仍是上一交易日。
- **时段判断**：用 `ctx.minute_bars()` 最后一根的 timestamp（见例 5），**不要用脚本机器当前时间**（回放/干跑时不准）。北京时间 = `ts/1000 + 8h`（ms 时间戳是 UTC）。
- **因子 lookback**：`ctx.factor(name, params, n)` 的 n 是取数窗口根数，要大于因子自身窗口（如 `ma(n=20)` 至少取 30+ 根，否则序列前面全是 NaN、`.iloc[-1]` 可能是 NaN）。
- **回放口径**：回放是"日线近似"——asof 移到**当日收盘 15:00**（日K 时间戳是当日 00:00，直接当 asof 会让分钟窗口退化为空），`price()`=当日收盘（分钟兜底日K）、`daily(n)`=截至当日、`factor` 同口径。日内时段类条件（例 5 的 14:30 判断）在回放里行为不同，回放结果仅用于估算触发频率。

## 诊断手册（用户说"没提醒"时按序排查）

1. **任务 enabled？** `monitor_cli.py list` 看 enabled 列；0 → `toggle <id>` 启用。
2. **last_error？** `monitor_cli.py show <id>` 看 `last_error`/`error_count`：脚本报错会记在这里（语法错/取数失败/运行异常）。
3. **poll_count 增长？** 不涨 = daemon 没在跑（人工重启 `scripts/monitor_daemon.py`）或非交易时段/停牌空转；涨 = 脚本在正常执行，只是条件没满足。
4. **信号历史**：DB 里 `signals` 表只记边沿——条件一直成立（灯常亮）不会再推，条件从没满足过自然无信号。用 `validate_watch.py` 回放确认条件本身松紧是否合理。
5. **notify 开关**：任务 `notify=0` 只亮灯不推送；注册时没加 `--no-notify` 才是默认推送。
6. **Bark 配置**：`data/monitor_config.json` 缺失或缺 `bark_key` = 推送整体关闭（只亮灯）；推送发送失败会记任务 `last_error`，但信号照常入库不丢。

## 注意事项

- **省 token**：验证/诊断优先用 `monitor_cli.py` 和 `validate_watch.py`，别为无关功能翻源码；生成脚本时从示例库改写。
- **真实数据**：干跑/回放前 `source ~/.zshrc`；`data/` 不提交。
- 守护进程崩溃需人工重启（`scripts/monitor_daemon.py`）；灯状态在 DB，重启不丢状态——用户报"灯没丢但没在跑"时优先怀疑这个。
