# Stock — A 股量化投研工具箱（本地优先）

**一句话：把 A 股量化研究里最脏最累的活——拉数据、管数据、验证想法、盘中盯梢——全部交给本地程序，你只管研究策略本身。**

- 行情数据**查到即存**：同一只股票同一区间，第二次查询零网络、毫秒级返回
- 回测引擎**无前视撮合**：信号次 bar 开盘成交、T+1、涨跌停顺延、手续费印花税滑点齐全
- 因子**算一次永久复用**：改参数自动换目录重算，回测直接命中缓存
- 策略**每次改动自动对比**：进步 / 退步 / 部分改善，程序判定，不靠感觉
- 盘中**条件触发推手机**：一个 Python 脚本描述条件，交易时段自动轮询，灯亮灭边沿 Bark 推送一次，不轰炸
- **AI 不碰数据**：所有数值与结论由程序和算法计算得出，AI 只负责交互与理解需求（本仓库强制工作规则）

数据源为 [TickFlow](https://tickflow.org)（付费 API，官方 SDK）。

---

## 解决什么问题

| 痛点 | 本项目的解法 |
|------|----------|
| **重复拉数据，慢且贵**：TickFlow 按请求/权限计费，同区间反复拉取纯浪费 | **本地优先 + 查到即存**：先查本地 Parquet/SQLite，命中即零网络；缺口回源并落库，相同数据永不重复请求 |
| **全市场回填是体力活**：5000+ 只股票 × 多周期，中断就得重来 | **断点续传**：coverage 记账 + 批量接口 + 速率自适应；重跑同一命令只补缺口 |
| **分钟数据量巨大**：全市场分钟一年约 3 亿行 | **分区 Parquet + DuckDB**：按 year/month 分区、列式存储、分区裁剪，本地查询毫秒级 |
| **复权要么求人要么算错** | **本地前/后复权**：除权因子本地缓存，复权本地计算，与服务端对拍误差 < 1e-6 |
| **盘中数据每根都在变**，写进永久缓存会污染历史 | **盘中半可变层**：当日段走 intraday 接口（TTL 60s），不记永久覆盖区间；收盘后日终任务固化 |
| **数据有没有缺口、对不对，没人知道** | **质量保障**：抽样回源比对 + 1m/1d 交叉校验 + 缺口检测修复 + 日终核对，全部出报告 |
| **回测不可信**：次日成交 vs 即时成交，差之毫厘谬以千里 | **无前视撮合**：事件驱动、信号次 bar 开盘价成交、T+1 锁定、涨跌停顺延、100 股整手 |
| **策略改了一版，是进步还是退步？** | **策略库版本对比**：每次 record 自动对比 v1 与上一版，四项主指标判定进步/退步/部分改善 |
| **条件触发了，人不在电脑前** | **日内盯盘**：一个 `check(ctx)` 脚本描述条件，交易时段轮询；条件成立亮灯、失效灭灯，**只在翻转瞬间推送一次** Bark 通知 |

---

## 它能做什么

| 模块 | 能力 | 状态 |
|---|---|---|
| **数据中心** | K 线/财务/元数据本地缓存，全市场回填，本地复权，盘中半可变层，日终维护，数据校验 | ✅ 一/二/三期 |
| **回测引擎** | 事件驱动多标的回测，指标库（MA/EMA/RSI/MACD/KDJ/ATR/BOLL），绩效统计 | ✅ 四期 |
| **因子库** | 11 个内置量价因子，定义+计算值统一管理，惰性取数，每个因子附同花顺一句话条件 | ✅ 五期 |
| **策略库** | 策略列表 + 版本管理，新版本自动对比判定进步/退步 | ✅ 七期 |
| **日内盯盘** | Python 脚本条件 + 信号灯 + Bark 推送 + 历史回放验证 | ✅ 八期（待交易日盘中冒烟） |
| **本地 API** | FastAPI 只读查询 + 盯盘管理接口（127.0.0.1:8666），供外部工具对接 | ✅ 六期 |

**这个产品不做什么**：不做自动选股（回测验证"哪些条件有利于收益"，产出同花顺一句话条件，由人去同花顺筛股执行）；不做自动交易（盯盘只提醒，买卖手动）。

---

## 用 Skill 操作（推荐入口）

**与本项目交互的主要方式是 Skill**——在 Claude Code 里用自然语言说出需求，对应专家 skill 会接管全流程（生成脚本 → 程序验证 → 执行 → 交付结果）。所有数值与结论都由程序计算，AI 只负责理解你和呈现结果。

| Skill | 干什么 | 这样说就会触发 |
|---|---|---|
| **初始化引导** `stock-start-up` | 新用户从零跑起来：检查环境、配 API Key、回填首批数据、冒烟验证 | "我刚下载这个项目，帮我配置一下" |
| **回测专家** `backtest-expert` | 验证交易想法：跑真实回测、出 PDF 报告、给可执行的选股/进出场条件（同花顺一句话） | "帮我回测双均线策略在 600000 上近 5 年的表现" |
| **盯盘专家** `monitor-expert` | 把盯盘条件做成常驻任务：生成脚本 → 三段验证（语法/干跑/历史回放）→ 注册；条件触发推 Bark | "600869 跌到 20 日低位区时提醒我" |
| **复盘专家** `trade-review` | 交割单/交易记录复盘：进出场时机评估、亏损归因、改进建议 | "帮我复盘一下这个月的交易记录" |

新用户第一步，两条命令 + 一句话：

```bash
git clone https://github.com/lzx2005/stock.git   # 或 SSH：git@github.com:lzx2005/stock.git
cd stock
```

然后用 Claude Code 打开这个目录，说一句 **"帮我初始化这个项目"**——`stock-start-up` skill 会带你配好 key、回填数据、跑通验证，之后直接用上面三个专家 skill 操作即可。

---

## 快速上手（命令行方式）

### 环境准备（新机器从零跑起来）

| 准备项 | 必需性 | 怎么做 |
|---|---|---|
| **Python ≥ 3.11** | 必需 | `uv sync` 安装依赖（或 `python -m venv .venv && .venv/bin/pip install tickflow[all] duckdb pandas pyarrow fastapi uvicorn reportlab matplotlib`，测试再装 `pytest pytest-timeout httpx`） |
| **TickFlow API Key** | 必需（付费） | 到 [tickflow.org](https://tickflow.org) 注册开通：`export TICKFLOW_API_KEY="你的key"`（建议写入 `~/.zshrc`；非交互 shell 不加载 `.zshrc`，脚本里要先 `source ~/.zshrc`） |
| **行情数据** | 必需 | **仓库不含任何数据**（`data/` 已 gitignore）。直接查询会自动回源落缓存；或先回填：`.venv/bin/python scripts/backfill.py --periods 1d` |
| **Bark device key** | 可选（盯盘推送） | iOS 装 [Bark](https://bark.day.app) 拿 device key，写 `data/monitor_config.json`：`{"bark_key": "<你的device_key>"}`；不配则盯盘只亮灯不推送 |
| **WS 实时推送权限** | 可选 | 需在 TickFlow 套餐中开通；无权限时实时采集不可用，历史/盘中 intraday 查询不受影响 |

> 密钥纪律：`TICKFLOW_API_KEY` 只走环境变量、Bark key 只在 `data/monitor_config.json`，两者都不会进库；**请勿把 key 写进代码或文档**。

### ① 查数据（自动缓存）

```python
from datacenter import DataCenter

dc = DataCenter()

# 600000.SH（浦发银行）近 3 年日 K，前复权；首次回源，之后全走缓存
df = dc.get_klines("600000.SH", period="1d")
print(df.tail())
```

```bash
source ~/.zshrc        # 载入 TICKFLOW_API_KEY（首次配置见上文「环境准备」）
```

### ② 跑回测

内置双均线示例（真实数据单标的 + 多标的共享资金池，MA 值从因子库惰性取数：首跑计算落盘，再跑命中缓存）：

```bash
source ~/.zshrc && .venv/bin/python -m examples.run_backtest
```

自己写策略（事件驱动，次 bar 开盘价成交，无前视）：

```python
from backtest.engine import BacktestEngine
from backtest.indicators import ma
from backtest.performance import analyze
from backtest.strategy import Strategy
from datacenter import DataCenter

class MaCross(Strategy):              # init / on_bar / on_finish 生命周期
    def on_bar(self, ctx):
        h = ctx.history()             # 截至当前 bar 的历史（不含未来）
        if len(h) < 21:
            return
        s, l = ma(h.close, 5).iloc[-1], ma(h.close, 20).iloc[-1]
        s_p, l_p = ma(h.close, 5).iloc[-2], ma(h.close, 20).iloc[-2]
        held = ctx.symbols[0] in ctx.positions
        if s_p <= l_p and s > l:      # 金叉
            ctx.buy(ctx.symbols[0])   # 全仓买入，t+1 开盘成交
        elif held and s_p >= l_p and s < l:   # 死叉
            ctx.sell(ctx.symbols[0])

dc = DataCenter()
start = int(__import__("time").time() * 1000) - 5 * 365 * 86_400_000
eng = BacktestEngine(dc, ["600000.SH"], period="1d", start_ms=start,
                     initial_cash=1_000_000, adjust="forward")
broker = eng.run(MaCross())
rep = analyze(broker, eng.data, period="1d")   # 总收益/年化/回撤/夏普/胜率/交易明细
print(f"总收益 {rep.total_return:+.2%}  年化 {rep.annual_return:+.2%}  夏普 {rep.sharpe:.2f}")
```

- 时间戳为 int 毫秒（与数据层一致）；数据走 `dc.get_klines(..., adjust="forward")` 前复权
- `ctx.history(symbol)` 只含当前 bar 及之前的行，`ctx.buy/sell/positions/cash` 操作共享资金池
- 指标库独立可用：`from backtest.indicators import ma, ema, rsi, macd, kdj, atr, boll`

### ③ 用因子

因子值从 `FactorStore.get` 取，首次调用现算并落盘 `data/factors/`，之后直接命中缓存：

```python
from datacenter import DataCenter
from factors import FactorStore
import factors.factors  # noqa: F401  —— import 即注册内置因子

fs = FactorStore(DataCenter())   # 根目录 data/factors，前复权（与回测口径一致）
s = fs.get("600000.SH", "ma", {"n": 20}, "1d", start_ms, end_ms)  # -> pd.Series（索引=timestamp 毫秒）
```

- `get(symbol, name, params=None, period="1d", start_ms, end_ms)`：**start_ms/end_ms 必填**；缓存按指纹 `sha1(name|params|version|adjust)` 定位，改参数/版本/复权口径自动换目录重算
- `list_factors()`：列出全部已注册因子；`refresh(...)` 强刷；`drop(...)` 作废缓存
- 内置因子与同花顺条件句映射：

| 因子 | 含义 | 同花顺条件句 |
|------|------|--------------|
| `ma(n)` | N 日简单均线 | `MA5>MA20`、`收盘价>MA20` |
| `ema(n)` | N 日指数均线 | `EMA5`、`收盘价>EMA20` |
| `rsi(n)` | RSI(Wilder) | `RSI>70` 超买、`RSI<30` 超卖 |
| `atr(n)` | 平均真实波幅 | 同花顺无直接对应，用于波动过滤 |
| `macd_hist` | MACD 柱（国内惯例 `2*(dif-dea)`） | `MACD柱>0`、红柱放大 |
| `kdj_j` | KDJ 的 J 值 | `J>100` 超买、`J<0` 超卖 |
| `boll_up` / `boll_low` | 布林上/下轨 | `收盘价>BOLL上轨`（突破）、`收盘价<BOLL下轨`（超跌） |
| `vol_ratio(n)` | 量比：当日量/近 n 日均量 | `量比>1.5`（放量） |
| `mom(n)` | N 日动量/涨幅 | `5日涨幅>10%` |
| `bias(n)` | 乖离率：(收盘-均线)/均线 | `BIAS20` 超买超卖 |

批量预热（之后回测直接命中缓存）：

```bash
source ~/.zshrc && .venv/bin/python scripts/factor_warm.py --symbols 600000.SH,000001.SZ --factors ma,vol_ratio --years 5
```

### ④ 管策略（版本对比）

```bash
.venv/bin/python scripts/strategy_cli.py create --name "双均线金叉" --desc "..."
.venv/bin/python scripts/strategy_cli.py list        # id/版本/总收益/夏普/进步判定
```

每次 `record` 新版本自动对比 v1 与上一版：四项主指标（总收益/超额收益/最大回撤/夏普）判定进步/退步/部分改善。

### ⑤ 起盯盘（条件触发推手机）

盯盘任务 = 一个 Python 脚本定义 `check(ctx)` 返回 `{"on": bool|None, "msg": str}`——条件成立亮灯、失效灭灯，边沿翻转时 Bark 推送一次：

```bash
sh scripts/start.sh                    # 一键启动：盯盘守护进程 + Web API（后台）
.venv/bin/python scripts/monitor_cli.py list      # 任务列表（灯状态/错误）
.venv/bin/python scripts/monitor_cli.py register --name "600869 20日低位区" \
    --symbol 600869.SH --script-file my_watch.py --description "原理/实现/回放结果"
```

注册前用 `scripts/validate_watch.py` 做三段验证（语法 → 真实干跑 → 历史回放触发次数），防止注册一个每分钟都亮或永远不响的废条件。脚本写法与示例见 `.claude/skills/monitor-expert/SKILL.md`。

### 常用命令

```bash
uv run python scripts/backfill.py                 # 全市场历史回填（断点续传）
uv run python scripts/backfill.py --periods 1d    # 只补日线
uv run python scripts/backfill.py --periods 1m,5m,15m,30m,60m --symbols 600000.SH,000001.SZ --rate 0.5   # 分钟抽样回填（一年深度）
uv run python scripts/daily.py                    # 日终维护（配 cron，工作日 16:00）
uv run python scripts/validate.py                 # 数据校验（抽样比对 + 交叉校验）
uv run python scripts/ws_collect.py --symbols 600000.SH,000001.SZ   # 盘中 WS 采集
sh scripts/start.sh / stop.sh                     # 盯盘守护进程 + Web API（8666）
```

### 跑测试

```bash
.venv/bin/python -m pytest tests/     # 全量回归（232 项，--timeout=60）
```

---

## 功能清单（按迭代期）

### 数据中心（一/二/三期）✅

- **K 线缓存**：`1m/5m/15m/30m/60m/1d/1w/1M` 等周期，本地 Parquet 分区存储，DuckDB 查询
- **本地复权**：前复权（默认）/后复权/原始价，本地计算零额外请求
- **财务 + 元数据 + 标的池**：利润表/资产负债表/现金流/核心指标，标的名称交易所、标的池成员，带 TTL 缓存
- **历史回填**：`backfill.py` 全市场或多周期回填，断点续传、速率自适应（批量 60 次/分）
- **实时采集**（WS）：`ws_collect.py` 盘中采集实时行情，缓冲批量落盘、断线重连（当前套餐无 WS 权限，代码就绪）
- **盘中半可变层**：当日段查询自动走 intraday 接口，TTL 60s 缓存，不污染永久数据
- **日终维护**：`daily.py` 收盘后固化当日多周期 + 刷新除权因子 + 元数据，幂等可配 cron
- **数据校验**：`validate.py` 抽样比对 + 交叉校验 + 缺口修复，报告入库

### 回测引擎（四期）✅

- **指标库**（纯 pandas 向量化）：`MA / EMA / RSI / MACD / KDJ / ATR / BOLL`
- **撮合与账户**（`broker.py`）：次 bar 开盘成交、佣金 0.03% 双边最低 5 元、卖出印花税 0.05%、滑点可配、A 股 100 股整手、T+1 锁定、涨跌停（一字板）顺延
- **策略接口**（`strategy.py`）：`Strategy.init/on_bar/on_finish` + `Context`（买卖/持仓/现金/历史，不含未来数据）
- **回测引擎循环**（`engine.py`）：多标的时间对齐、逐 bar 撮合→下单、无前视
- **绩效统计**（`performance.py`）：权益曲线/收益/回撤/夏普/胜率/交易明细
- **示例策略**：双均线金叉/死叉（走因子库取数），真实数据 smoke 通过

### 因子库（五期）✅

统一管理量价因子**定义 + 计算值**：算一次、落盘 `data/factors/`，之后回测直接命中缓存（本地优先、缺口现算再存，复刻 `CacheResolver` 的 fetch-through 模式）。**不做条件选股**——因子语义 = 可转述为同花顺一句话选股的原子条件；本系统回测验证"哪些条件利于收益"，用户再拿条件去同花顺筛股。

- **定义注册表**（`registry.py`）：`FactorDefinition` + 指纹 `sha1(name|params|version|adjust)[:16]`——改参数/改公式/改复权口径自动换目录重算，旧值保留不误删
- **计算层**（`compute.py`）：`apply_factor` 校验输入列并调用注册函数；内置因子直接引用 `backtest.indicators`，条件因子（量比/动量/乖离）用 pandas 滚动算子
- **存储与取数**（`store.py`）：parquet 分区 + 原子写 + 区间合并；`get` 惰性取数（覆盖切片 / 缺口补算）、`warm` 批量预热、`refresh` 强刷、`drop` 作废
- **内置因子**：`ma / ema / rsi / atr / macd_hist / kdj_j / boll_up / boll_low / vol_ratio / mom / bias`
- **golden 对拍**：双均线策略走因子库取数与现算版逐笔交易、权益曲线完全一致

### 本地 Web API（六期）✅

本地 HTTP 接口查询已存行情与因子数据、管理盯盘任务——**默认只读离线**：直接读存储层，不触发网络回源、无需 API key；唯一例外是 `refresh=1`（懒构造 DataCenter 回源补最新，失败自动退回缓存）。

- 行情/因子查询端点：`/api/periods`、`/api/coverage`、`/api/klines`、`/api/factors`、`/api/factor-dirs`、`/api/factor-values`
- 盯盘管理端点：`/api/monitor/*`（任务 CRUD/启停 + 信号历史）
- 启动：`.venv/bin/python scripts/serve.py`（127.0.0.1:8666）；接口规格见 `docs/FRONTEND.md` §5（暂作接口文档保留，前端方案未定）

### 策略库（七期）✅

策略列表 + 版本管理（纯文件系统 `data/strategies/`，JSON + 原子写）：`create` / `record` / `compare` / `rename` / `delete`。record 新版本时自动同时对比 **v1（原版）** 与 **上一版**，按四项主指标判定进步/退步/部分改善；回测报告（`build_report`）含"七、版本对比"章节。入口：`scripts/strategy_cli.py`。

### 日内盯盘（八期）✅ 待交易日盘中冒烟

- **任务 = Python 脚本**：`check(ctx)` 返回 `{"on": bool|None, "msg": str}`，脚本代码存 `data/monitor.db`，页面可查看编辑
- **单信号灯**：条件成立亮灯、失效灭灯；买卖含义由任务名称/说明表达，系统不预设方向；**只在亮/灭边沿推送一次**，条件持续成立不轰炸
- **上下文** `ctx`：`price()` / `minute_bars()`（当日 1m）/ `daily(n)`（含今日合成日K）/ `factor(name, params, n)`
- **守护进程**：`monitor_daemon.py` 每分钟 tick，仅交易时段（9:25-11:30、13:00-15:00）调度；脚本异常任务级隔离记 `last_error`，停牌无数据静默跳过
- **推送**：Bark（key 在 `data/monitor_config.json`，缺失只亮灯不推送）
- **三段验证**：`validate_watch.py` = 语法检查 → 真实干跑 → 历史回放（近 N 年触发次数 + 最近触发日期）
- **管理**：`monitor_cli.py`（register/list/show/toggle/delete）+ `/api/monitor` 接口 + 盯盘专家 skill

---

## 技术架构

```
DataCenter 门面（唯一入口）
  ├── CacheResolver      缓存命中 / 缺口决策，本地优先
  ├── KlineStore         Parquet 分区 + DuckDB 读取 + last-wins 去重
  ├── IntradayCache      盘中半可变层（当日 TTL 60s，不污染 coverage）
  ├── RealtimeStore      WS 实时快照（date=YYYY-MM-DD 分区）
  ├── MetaStore / FinancialStore  元数据 / 财务（SQLite, TTL 缓存）
  └── TickFlowClient     SDK 薄封装：限速 + 重试 + 批量
```

```
src/
├── datacenter/          数据中心（一/二/三期）
│   ├── api.py           DataCenter 门面
│   ├── resolver.py      CacheResolver
│   ├── adjust.py        本地前/后复权
│   ├── quality.py       日历 / 缺口 / 抽样比对 / 交叉校验
│   ├── client/          TickFlowClient（限速重试分页）
│   ├── store/           KlineStore / RealtimeStore / MetaStore / FinancialStore
│   └── jobs/            backfill / daily_maintenance / ws_collector
├── backtest/            回测引擎（四期）
│   ├── indicators.py    MA / EMA / RSI / MACD / KDJ / ATR / BOLL
│   ├── broker.py        撮合与账户
│   ├── strategy.py      Strategy 基类 + Context
│   ├── engine.py        回测引擎循环
│   └── performance.py   绩效统计 + 权益曲线
├── factors/             因子库（五期）
│   ├── registry.py      因子定义注册表 + 指纹
│   ├── compute.py       因子计算（输入校验 + 引用 indicators / 滚动算子）
│   ├── store.py         FactorStore（parquet 分区 + 惰性取数 + 原子写）
│   └── factors.py       内置量价因子（import 即注册）
├── strategy/            策略库（七期）：store（JSON 版本目录）+ compare（进步/退步判定）
├── monitor/             日内盯盘（八期）
│   ├── store.py         MonitorStore：data/monitor.db（tasks/signals，WAL，自动迁移）
│   ├── runtime.py       MonitorContext + 脚本加载/校验（单灯契约 {"on","msg"}）
│   ├── notify.py        Bark 推送
│   └── daemon.py        每分钟 tick：交易时段调度、灯边沿判定、错误隔离
└── webui/               Web 查询后端（六期）
    ├── app.py           create_app 工厂：三只读存储 + MonitorStore
    ├── api.py           /api 只读端点（periods/coverage/klines/factors/factor-dirs/factor-values）
    └── monitor_api.py   /api/monitor 六端点（tasks CRUD/toggle + signals）
examples/
├── strategies/ma_cross.py   双均线示例策略
└── run_backtest.py          真实数据单标的 + 多标的回测
```

数据存储：`data/`（已 gitignore）
- `klines/` — K 线 Parquet，日线及以上按 `year`、分钟按 `year/month` 分区，只存原始价
- **目录名大小写避让**：macOS/Windows 文件系统大小写不敏感，`period=1m`（分钟）与 `period=1M`（月线）会落到同一目录互相污染（hive 分区混杂直接打挂 DuckDB 查询）。月线落盘目录固定为 `period=1Mo`，拼路径一律走 `datacenter.constants.period_dir_token()`，不要手写 `f"period={period}"`（KlineStore / FactorStore 均已接入）
- `factors/` — 因子值 Parquet 分区（按指纹目录）
- `strategies/` — 策略库 JSON（版本目录）
- `realtime/` — WS 快照，`date=YYYY-MM-DD` 分区
- `meta.db` / `monitor.db` — SQLite（WAL）：coverage/元数据/财务/报告；盯盘任务与信号

---

## 权限与数据深度说明

- **分钟 K 线**：当前套餐**已可用**，历史深度限**最近一年**（2026-08-30 实测）
- **实时行情 WS 推送**：当前套餐**无权限**；代码已实现并通过测试，待开通后可盘中启用（当日段 intraday 查询不受影响）
- 详见 [docs/sdk-notes.md](docs/sdk-notes.md)（SDK 实测记录：限流、异常、字段）

---

## 设计文档与进度

- 设计文档：[docs/superpowers/specs/](docs/superpowers/specs/)（数据中心 / 因子库 / WebUI / 策略库 / 盯盘）
- 实施计划：
  - [第一期 · K线缓存 + 历史回填](docs/superpowers/plans/2026-08-30-data-center-phase1.md) ✅
  - [第二期 · 复权 + 财务/元数据 + 校验 + 日终](docs/superpowers/plans/2026-08-30-data-center-phase2.md) ✅
  - [第三期 · WS 采集 + 盘中半可变层](docs/superpowers/plans/2026-08-30-data-center-phase3.md) ✅
  - [第四期 · 回测引擎 + 真实回填验证](docs/superpowers/plans/2026-08-30-backtest-phase4.md) ✅
  - [第五期 · 因子库](docs/superpowers/plans/2026-08-30-factors-phase5.md) ✅
  - [第六期 · Web 查询界面](docs/superpowers/plans/2026-08-31-webui-phase6.md) ✅ 后端完成（前端为独立工程）
  - [第七期 · 策略库](docs/superpowers/plans/2026-09-01-strategy-phase7.md) ✅
  - [第八期 · 日内盯盘系统](docs/superpowers/plans/2026-09-05-monitor-phase8.md) ✅（待交易日盘中冒烟）
- 架构图文字描述（供画图 AI 使用）：[docs/architecture-diagram.md](docs/architecture-diagram.md)
- 接口文档：[docs/FRONTEND.md](docs/FRONTEND.md) §5（前端方案未定，暂作 API 参考保留）
- AI 协作入口（仓库工作规则）：[CLAUDE.md](CLAUDE.md) / [HELP.md](HELP.md)
