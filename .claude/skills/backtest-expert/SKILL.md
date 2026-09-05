---
name: backtest-expert
description: 回测专家——把用户的回测需求变成真实回测并出 PDF 报告。当用户提出"回测某策略/验证某个交易想法"、"某条件/指标是否有利于收益"、"根据 XX 条件做回测"、"给个选股策略和进出场时机"、"分析某标的的技术走势"等需求时，务必使用本 skill（即使用户没有明说"回测"两个字，只要是在本仓库语境下问策略/条件/选股收益，都应触发）。它能跑回测引擎、复用因子库、生成含模拟收益图的 PDF 报告，并给出可落到同花顺一句话条件的选股/进场/出场操作指引。
---

# 回测专家

## 你的职责

用本仓库的**回测引擎 + 因子库**，把用户的回测需求做成真实回测，交付三样东西：

1. **PDF 报告** `回测报告.pdf`——回测内容 / 过程 / 结果 / 报表 / 模拟收益图
2. **可操作的操作指引**——选股策略、进场时机、出场时机，可翻译成同花顺一句话条件
3. 配套可读版 `report.md` 与结构化 `results.json`（供复核/二次分析）

本仓库哲学（务必贯彻）：**回测是为了验证"哪些条件有利于收益"，结论必须落到"人能照着做的条件"上**（如 `量比>1.5`、`MA5 上穿 MA20`），而不是停在指标代码。这也是用户的核心诉求（见 HELP.md §2）。

## 边界

- 不做选股系统（用户明确不做，回测结论用于人去同花顺手动执行）。
- 不接实盘/下单，不产生任何交易动作。
- 报告要写明：**回测基于已存历史数据（含手续费/印花税/滑点与 T+1 撮合），不代表未来**。

## 产出目录

回测先写到临时 scratch 目录（项目根 `reports/<策略名>-<YYYYmmdd-HHMMSS>/`），**随后必须登记进策略库**（`data/strategies/<id>/versions/<N>/`，见 Step 5"版本登记"）。scratch 目录文件：

| 文件 | 内容 |
|---|---|
| `回测报告.pdf` | 正式交付（reportlab + matplotlib 生成） |
| `report.md` | 同内容可读版（含操作指引） |
| `results.json` | 结构化结果（指标/交易/权益曲线元数据/操作指引） |
| `equity_curve.png` | 模拟收益图（matplotlib，中文） |
| `strategy_*.py` | 本次策略源码（可复跑） |
| `backtest_meta.json` | 边车：复权口径/成本模型/策略参数/区间（版本登记必需） |

`reports/` 已在 .gitignore，是中间态；**版本历史以策略库为准**——登记进版本目录后才有跨版本对比的 `comparison.json` 与含"七、版本对比"章节的 PDF。完成后把版本目录里 PDF 的绝对路径告诉用户。

## 工作流程（五步）

### Step 1 · 澄清需求

把用户话术转成可回测定义：**标的、周期、区间、初始资金、买卖规则、是否用因子**。

- 缺参数时**用合理默认，并在报告"假设"里写明**。用户关注省 token：能默认就不追问，除非买卖规则本身写不出来。
- 默认建议：周期 `1d`；区间近 3 年；初始资金 100 万；单标的全仓进出，多标的共享资金池按信号全仓。
- **选策略（新建 or 升级版本）**：先 `.venv/bin/python scripts/strategy_cli.py list` 看已有策略与最新指标。
  - 用户说"继续优化/改进 XX 策略" → 指认其 `--id`；读该策略 v1 与上一版摘要（`show-version`，直接读 version.json，省 token）。本次回测即该策略的新版本，版本号在 record 时自动 +1。
  - 全新策略 → `create --name "..." --desc "..."` 记下 `--id`，本次即 v1。
  - 对比基线：本次"上一版"= 该策略 latest_version，"原始版"= v1；对比在 Step 5 record 时自动完成。

### Step 2 · 数据准备（真实数据纪律）

- 先 `source ~/.zshrc`——非交互 shell 拿不到 `TICKFLOW_API_KEY`，回源必失败。
- **先查缓存覆盖再跑**：`dc.klines.read([symbol], period, s, e)` 是纯读缓存（不回源）；若为空说明该标的/周期/区间无数据。取"缓存实际覆盖"与请求区间的交集做回测，报告写明实际区间。
- 取数用 `dc.get_klines(symbol, period, s, e)`（缓存优先、缺失自动回源）。
- 区间 `end_ms = int(time.time()*1000)`；分钟周期默认近 1 年（套餐深度限制，见 sdk-notes）。

### Step 3 · 实现策略

写 `Strategy` 子类。**优先用因子库**（`FactorStore`），其次 `backtest.indicators`。

- 必须 `import factors.factors`（显式注册，否则 `FactorUnknownError`）。
- `init(ctx)` 用全量历史预计算指标；`on_bar(ctx)` 只用当前 bar 及之前的信息。
- **无前视纪律**：信号在 t 产生、成交在 t+1 开盘（引擎自动保证）；on_bar 里禁用未来数据。
- 下单：`ctx.buy(symbol)` / `ctx.sell(symbol)`（shares=None 全仓）、`ctx.close_position()`。

### Step 4 · 跑回测

```python
eng = BacktestEngine(dc, symbols, period="1d", start_ms=s, end_ms=e, initial_cash=1_000_000)
eng.run(MyStrategy(fs=FactorStore(dc)))
rep = analyze(eng.broker, eng.data, period="1d")         # 绩效
curve = equity_curve(eng.broker, eng.data, period="1d")   # DataFrame[timestamp, equity]
```

- **必须算一个基准**做对比：单标的 = 买入持有（期末/期初收盘）；多标的 = 等权平均买入持有。报告里给"策略 vs 基准"的超额。
- 落盘：`results.json`（schema 见 build_report.py 文档）+ `equity.csv`（`timestamp,equity[,benchmark]`）。
- **再写一个 `backtest_meta.json` 边车**（Step 5 版本登记必需）：
  `{"strategy_class": "...", "params": {...}, "change_note": "相对上一版的改动", "adjust": "forward", "broker": {"commission":..., "min_commission":..., "stamp_tax":..., "slippage":..., "lot_size":..., "t_plus_1":...}, "start_ms":..., "end_ms":...}`
  其中 symbols/period/start/end/initial_cash 从 results.json 取；`start_ms`/`end_ms`（毫秒）补进边车。**策略参数 `params` 必须如实记录**——那是版本对比中的"被测对象"。

### Step 5 · 版本登记 + 报告 + 操作指引

1. **登记版本**：`source ~/.zshrc; .venv/bin/python scripts/strategy_cli.py record --id <策略id> --from <scratch目录> --note "相对上一版的改动"` —— 把 scratch 产物复制进 `data/strategies/<id>/versions/<N>/`，自动对比 v1 和上一版（写 `comparison.json`、追加 report.md 对比节），打印对比结论。
2. **在版本目录出 PDF**：`.venv/bin/python .claude/skills/backtest-expert/scripts/build_report.py data/strategies/<id>/versions/<N>/`（v≥2 的 PDF 含"七、版本对比"章节；v1 无对比章节，属预期）。
3. 写 `report.md`（按下方模板）与 `results.json` 的 `entry_exit` 字段。
4. 给用户口头结论：一句话结果 + **对比结论（vs v1 / vs 上一版：进步/退步）** + 操作指引 + 版本目录里 PDF 的绝对路径。

## PDF 报告模板（固定章节，build_report.py 按 results.json 组装）

1. **回测内容**——用户需求原话、假设清单
2. **回测方法**——标的/周期/区间/初始资金/策略逻辑/撮合规则
3. **回测结果**——绩效表：总收益/年化/最大回撤/夏普/交易次数/胜率/盈亏比，含基准对比
4. **模拟收益图**——权益曲线 vs 基准
5. **交易明细**——最近 N 笔：买卖时间/价位/股数/盈亏
6. **操作指引**——选股策略/进场时机/出场时机/同花顺一句话条件

## 操作指引规范（写成"人能照着做"的话）

- **选股策略**：一句话，含可执行条件（如"5 日线上穿 20 日线时买入持有，下穿时卖出"）。
- **进场时机**：具体触发点（哪个条件、哪个时点、价位参考）。
- **出场时机**：止盈/止损/反转条件（如"收盘跌破成本价 − 2×ATR(14) 止损"）。
- **同花顺一句话条件**：把买卖条件翻译成同花顺能写的句子（如 `MA5 上穿 MA20`）。
- **局限声明**：基于已存历史 + 成本模型，不代表未来；列出的条件都是回测验证过的假设，需结合大盘/基本面。

## 策略话术 → 实现速查

| 用户话术 | 实现要点 |
|---|---|
| 双均线金叉/死叉 | `ma(short)` 上穿 `ma(long)` 买 / 下穿卖（FactorStore 的 `ma` 因子） |
| RSI 超卖/超买 | `rsi(n)` 下穿 30 买 / 上穿 70 卖（或 <30 / >70） |
| 价格突破 | close 突破 N 日最高买 / 跌破 N 日最低卖 |
| 均线支撑持有 | close 在 `ma(n)` 上方持有，跌破卖 |
| ATR 止损 | 跌破 `入场价 − k×ATR(n)` 平仓 |
| 固定百分比止损 | 跌破 `成本×(1−loss%)` 平仓 |
| 量比/放量 | `vol_ratio` 因子（量比放大）作买入过滤条件 |

### 成本 / 止损线实现的坑（务必遵守）

止损类策略的"持仓成本"必须**用真实成交价**，且**清仓后残值归零**。曾发生实测 bug：用 `ctx.trades` 滚动加权求成本时，上一回合卖出后 `shares` 归零但 `cost` 残值未清零，残差（买入额−卖出额）混进下一笔成本，导致止损线虚高、持仓 1-2 根 bar 就被"止损"、整段结果错误（如 ATR 止损被做成 -9% vs 正确 -43%）。

正确写法（清仓即重置）：

```python
shares = cost = 0.0
for t in ctx.trades:
    if t.symbol != symbol: continue
    if t.side == "buy": shares += t.shares; cost += t.shares * t.price
    else:
        shares -= t.shares; cost -= t.shares * t.price
        if shares <= 1e-9: cost = 0.0   # 清仓后重置
return cost / shares if shares > 1e-9 else None
```

或更简单：单标的全仓策略直接用 `ctx.bars[symbol]["open"]`（成交价）当成本。

**写完止损策略必须做 1 笔人工对拍**：挑第 1~2 笔交易，从原始日线手动算"收盘是否 < 成本 − k×ATR"确认触发日，再对比 `analyze()` 返回的回合明细——两头对上才算通过，否则默认策略有 bug。

## 版本对比语义（策略库 record 时自动执行）

- 新版本自动同时对比 **v1（原始版）** 与 **上一版**，判定 progress（进步）/ regress（退步）/ mixed（部分改善）：主指标为 total_return / 超额收益 / max_drawdown / sharpe；无一项变差且（≥2 项变好 或 总收益变好）= 进步；总收益变差 或 变差项 ≥2 = 退步。
- **可比性纪律**：只有回测设置一致（symbols/period/复权口径/区间/初始资金/成本模型）对比才有意义。改了标的/区间/成本模型 = 不可比（PDF 与 report.md 会标注原因，不下结论）。**策略参数 params 不同不阻断对比**——那正是被测对象。
- 保持版本可比：同一策略的优化迭代应固定标的/区间/成本模型，只改策略本身；换了标的/区间建议另建策略。

## 回测引擎 API 速查（不必每次翻源码）

```python
import factors.factors                       # 必须：注册内置因子
from datacenter import DataCenter
from backtest.engine import BacktestEngine
from backtest.performance import analyze, equity_curve
from backtest.strategy import Strategy
from backtest.indicators import ma, ema, rsi, macd, kdj, atr, boll   # 纯 pandas 指标
from factors import FactorStore

dc = DataCenter()
df = dc.get_klines(sym, "1d", s, e, adjust="forward")   # 缓存优先，缺失回源
cached = dc.klines.read([sym], "1d", s, e)              # 纯读缓存（查覆盖用）

eng = BacktestEngine(dc, symbols, period="1d", start_ms=s, end_ms=e,
                     initial_cash=1_000_000)
eng.run(MyStrategy(fs=FactorStore(dc)))
rep = analyze(eng.broker, eng.data, period="1d")
# rep 字段: initial_cash, final_equity, total_return, annual_return,
#   max_drawdown, sharpe, trade_count, win_rate, profit_loss_ratio, trades
#   trades 是 RoundTrip(symbol, shares, buy_ts, buy_price, sell_ts, sell_price, pnl)
curve = equity_curve(eng.broker, eng.data, period="1d")  # df[timestamp, equity]

class MyStrategy(Strategy):
    def __init__(self, **kw): ...
    def init(self, ctx):
        # ctx.history(symbol) 此时返回全量历史，可预计算指标
        pass
    def on_bar(self, ctx):
        # ctx.bars: {symbol: {open,high,low,close,volume}}
        # ctx.history(symbol): 截至当前 bar 的已收盘历史（无未来）
        # ctx.positions / ctx.cash / ctx.now（毫秒时间戳）
        if 买入条件: ctx.buy(symbol)
        elif 卖出条件: ctx.sell(symbol)
    def on_finish(self, ctx): ...
```

**FactorStore 取数**：`fs = FactorStore(dc)`；`fs.get(symbol, 因子名, 参数dict, period, s, e)` 返回按 timestamp 索引的 Series。内置因子：`ma/ema/rsi/atr/macd_hist/kdj_j/boll_up/boll_low/vol_ratio/mom/bias`（参数/语义见 `src/factors/factors.py` 各 doc）。

## 注意事项

- **省 token**：复用缓存与已落盘因子（FactorStore 算一次存库）；别全市场回测；别为无关功能翻源码。
- **真实数据**：`source ~/.zshrc` 先行；`data/`、`reports/` 不提交。
- **失败处理**：某标的无数据/区间过短，跳过并说明，别硬跑产出空报表；报告要诚实反映实际跑的区间与标的。
- 不要用 `duckdb.sql()` 并发查询（线程不安全）；需要时走 `datacenter.store._duck.query_df`。
