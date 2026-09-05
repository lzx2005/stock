# Stock 数据中心 + 回测引擎

面向 A 股量化研究的**本地数据底座 + 回测引擎**。数据源为 [TickFlow](https://tickflow.org)（付费 API，官方 SDK），本项目在它之上建了一层**本地优先、查到即存**的缓存与质量保障，并在此之上提供事件驱动的回测框架。

> 定位一句话：**把"重复拉数据、慢、贵、怕不准"的问题解决掉，让策略研究只关心策略本身。**

---

## 这个项目解决什么痛点

| 痛点 | 解决方案 |
|------|----------|
| **重复请求浪费**：同一只股票同一区间反复拉取，TickFlow 按请求/权限计费，慢且贵 | **本地优先 + 查到即存**：所有查询先走本地 Parquet/SQLite 缓存，命中即零网络；缺口回源并落库，相同数据永不重复请求 |
| **全市场回填是体力活**：5000+ 只股票 × 多周期，跑一次要几十分钟，中断就得重来 | **断点续传**：coverage 记账 + 批量接口 + 速率自适应；中断后重跑同一命令，只补缺口，不浪费已下好的数据 |
| **分钟数据量巨大**：全市场分钟一年约 3 亿行，直接依赖 API 不可行 | **分区 Parquet + DuckDB 查询**：按 year/month 分区、列式存储、分区裁剪，本地查询毫秒级 |
| **复权要么求人要么算错**：策略必须用复权价，服务端复权结果每查必算 | **本地前/后复权**：除权因子本地缓存，复权本地计算，与服务端对拍误差 < 1e-6 |
| **盘中数据是"半可变"的**：当日 K 线每根都在变，写进永久缓存会污染历史 | **盘中半可变层**：当日段自动走 intraday 接口（TTL 60s 缓存），**不记永久覆盖区间**；收盘后由日终任务固化，永不出错 |
| **数据有没有缺口、对不对没人知道** | **质量保障**：抽样回源比对 + 1m/1d 交叉校验 + 缺口检测修复 + 日终 WS/REST 核对，全部出报告 |
| **策略回测要可信**：信号次日成交 vs 即时成交，差之毫厘谬以千里 | **回测引擎无前视撮合**：事件驱动、信号次 bar 开盘价成交、T+1 锁定、涨跌停顺延、手续费/印花税/滑点、多标共享资金池 |

---

## 功能清单

### 一、数据中心（数据层）—— 已完成

- **K 线缓存**：`1m/5m/15m/30m/60m/1d/1w/1M` 等周期，本地 Parquet 分区存储，DuckDB 查询
- **本地复权**：前复权（默认）/后复权/原始价，本地计算零额外请求
- **财务 + 元数据 + 标的池**：利润表/资产负债表/现金流/核心指标，标的名称交易所、标的池成员，带 TTL 缓存
- **历史回填**：`backfill.py` 全市场或多周期回填，断点续传、速率自适应（批量 60 次/分）
- **实时采集**（WS）：`ws_collect.py` 盘中采集实时行情，缓冲批量落盘、断线重连（当前套餐无 WS 权限，代码就绪）
- **盘中半可变层**：当日段查询自动走 intraday 接口，TTL 60s 缓存，不污染永久数据
- **日终维护**：`daily.py` 收盘后固化当日多周期 + 刷新除权因子 + 元数据，幂等可配 cron
- **数据校验**：`validate.py` 抽样比对 + 交叉校验 + 缺口修复，报告入库

### 二、回测引擎（策略层）—— 第四期，已完成

- **指标库**（纯 pandas 向量化）：`MA / EMA / RSI / MACD / KDJ / ATR / BOLL` ✅
- **撮合与账户**（`broker.py`）：次 bar 开盘成交、佣金 0.03% 双边最低 5 元、卖出印花税 0.05%、滑点可配、A 股 100 股整手、T+1 锁定、涨跌停（一字板）顺延 ✅
- **策略接口**（`strategy.py`）：`Strategy.init/on_bar/on_finish` + `Context`（买卖/持仓/现金/历史，不含未来数据）✅
- **回测引擎循环**（`engine.py`）：多标的时间对齐、逐 bar 撮合→下单、无前视 ✅
- **绩效统计**（`performance.py`）：权益曲线/收益/回撤/夏普/胜率/交易明细 ✅
- **示例策略**：双均线金叉/死叉（已走因子库取数），真实数据 smoke 通过 ✅

### 三、因子库（策略层）—— 第五期，已完成

统一管理量价因子**定义 + 计算值**：算一次、落盘 `data/factors/`，之后回测直接命中缓存（本地优先、缺口现算再存，复刻 `CacheResolver` 的 fetch-through 模式）。**不做条件选股**——因子语义 = 可转述为同花顺一句话选股的原子条件；本系统回测验证"哪些条件利于收益"，用户再拿条件去同花顺筛股。

- **定义注册表**（`registry.py`）：`FactorDefinition` + `REGISTRY` + 指纹 `sha1(name|params|version|adjust)[:16]`——改参数/改公式/改复权口径自动换目录重算，旧值保留不误删 ✅
- **计算层**（`compute.py`）：`apply_factor` 校验输入列并调用注册函数；内置因子**只注册不重复实现**，直接引用 `backtest.indicators`，条件因子（量比/动量/乖离）用 pandas 滚动算子 ✅
- **存储与取数**（`store.py`）：`FactorStore(dc, root="data/factors")` parquet 分区 + 原子写 + 区间合并；`get` 惰性取数（覆盖切片 / 缺口补算）、`warm` 批量预热、`refresh` 强刷、`drop` 作废 ✅
- **内置因子**：`ma / ema / rsi / atr / macd_hist / kdj_j / boll_up / boll_low / vol_ratio / mom / bias`（`import factors.factors` 注册，`list_factors()` 可查全名）✅
- **示例策略**：双均线金叉/死叉已走因子库取数（`MaCross(..., fs=FactorStore(dc))`），首跑落盘、再跑命中缓存，golden 对拍与现算版逐笔交易、权益曲线完全一致 ✅

### 四、Web 查询界面（第六期，进行中）

本地 Web 页面查询已存行情与因子数据——**只读离线**：后端 FastAPI 直接读存储层，不触发网络回源、无需 API key；前端 React + antd + ECharts K 线图。

- **行情 tab**：覆盖索引表（搜索代码/名称、周期过滤、分页）→ 点行下钻 **左右分栏**（列表缩到左侧可折叠，右侧 K 线图 + 明细表）；ECharts K 线**红涨绿跌** + MA5/10/20 + 成交量副图 + 缩放联动，顶部深色"报价头"显示最新一根量价 ✅
- **因子 tab**：因子定义表 → 已存数据目录（指纹）→ symbol×period 组合 → 因子值分页，四级下钻 ✅
- **启动**：`.venv/bin/python scripts/serve.py`（后端 8666）；`cd frontend && npm run build` 后同端口直接服务页面；开发模式 `npm run dev` 经 proxy → 5173 ✅

---

## 快速上手

### 环境准备（别人/新机器从零跑起来）

| 准备项 | 必需性 | 怎么做 |
|---|---|---|
| **Python ≥ 3.11** | 必需 | `uv sync` 安装依赖（或 `python -m venv .venv && .venv/bin/pip install tickflow[all] duckdb pandas pyarrow fastapi uvicorn reportlab matplotlib`，测试再装 `pytest pytest-timeout httpx`） |
| **TickFlow API Key** | 必需（付费） | 到 [tickflow.org](https://tickflow.org) 注册开通，把 key 写进环境变量：`export TICKFLOW_API_KEY="你的key"`（建议写入 `~/.zshrc`；注意非交互 shell 不会加载 `.zshrc`，脚本/CI 里要先 `source ~/.zshrc` 或自行 export） |
| **行情数据** | 必需 | **仓库不含任何数据**（`data/` 已 gitignore）。要么直接查询（自动回源落缓存），要么先跑一次回填：`.venv/bin/python scripts/backfill.py --periods 1d` |
| **Node ≥ 20 + npm** | 仅 Web 界面需要 | `cd frontend && npm install && npm run build`，再启动后端即可浏览器访问 |
| **Bark device key** | 仅第八期盯盘推送需要（可选） | iOS 装 [Bark](https://bark.day.app) 拿 device key，写 `data/monitor_config.json`：`{"bark_key": "<你的device_key>"}`；不配则盯盘只亮灯不推送，其余功能不受影响 |
| **WS 实时推送权限** | 可选 | 需在 TickFlow 套餐中开通；无权限时实时采集不可用，历史/盘中 intraday 查询不受影响 |

> 密钥纪律：`TICKFLOW_API_KEY` 只走环境变量、Bark key 只在 `data/monitor_config.json`，两者都不会进库；**请勿把 key 写进代码或文档**。

### 查询数据（自动缓存）

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

### 跑回测（第四期回测引擎）

内置双均线示例（真实数据单标的 + 多标的共享资金池，MA 值从因子库 `FactorStore` 惰性取数：首跑计算落盘 `data/factors/`，再跑命中缓存）：

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

### 因子库（第五期）：惰性取数 + 批量预热

因子值从 `FactorStore.get` 取，首次调用从数据中心现算并落盘 `data/factors/`，之后直接命中缓存：

```python
from datacenter import DataCenter
from factors import FactorStore
import factors.factors  # noqa: F401  —— import 即注册内置因子

fs = FactorStore(DataCenter())   # 根目录 data/factors，前复权（与回测口径一致）
s = fs.get("600000.SH", "ma", {"n": 20}, "1d", start_ms, end_ms)  # -> pd.Series（索引=timestamp 毫秒）
```

- `get(symbol, name, params=None, period="1d", start_ms, end_ms)`：**start_ms/end_ms 必填**；params 传默认参数覆盖（如 `{"n": 5}`）；缓存按指纹 `sha1(name|params|version|adjust)` 定位，改参数/版本/复权口径自动换目录重算
- `list_factors()`：列出全部已注册因子；`refresh(symbol, name, ...)` 强刷（除权基准日漂移后手动重算）；`drop(name, ...)` 作废缓存
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

批量预热（对指定标的×因子算一遍入库，之后回测直接命中缓存；为全市场预计算留位）：

```bash
source ~/.zshrc && .venv/bin/python scripts/factor_warm.py --symbols 600000.SH,000001.SZ --factors ma,vol_ratio --years 5
```

### 本地 Web 查询界面（第六期）

```bash
source ~/.zshrc && .venv/bin/python scripts/serve.py        # 后端 8666（含 /api 全部只读端点）
# 有页面：先 cd frontend && npm run build，再启动上面命令 → http://127.0.0.1:8666
# 开发模式（热更新）：后端 8666 + cd frontend && npm run dev → http://localhost:5173（/api 经 proxy）
```

### 常用命令

```bash
uv run python scripts/backfill.py                 # 全市场历史回填（断点续传）
uv run python scripts/backfill.py --periods 1d    # 只补日线
uv run python scripts/backfill.py --periods 1m,5m,15m,30m,60m --symbols 600000.SH,000001.SZ --rate 0.5   # 分钟抽样回填（一年深度）
uv run python scripts/daily.py                    # 日终维护（配 cron，工作日 16:00）
uv run python scripts/validate.py                 # 数据校验（抽样比对 + 交叉校验）
uv run python scripts/ws_collect.py --symbols 600000.SH,000001.SZ   # 盘中 WS 采集
.venv/bin/python scripts/serve.py                 # Web 查询后端（8666）
cd frontend && npm run build                      # 前端生产构建（产出 frontend/dist）
```

### 跑测试

```bash
.venv/bin/python -m pytest tests/     # 全量回归（--timeout=60）
```

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
├── datacenter/          数据中心（数据层，三期已完成）
│   ├── api.py           DataCenter 门面
│   ├── resolver.py      CacheResolver
│   ├── adjust.py        本地前/后复权
│   ├── quality.py       日历 / 缺口 / 抽样比对 / 交叉校验
│   ├── client/          TickFlowClient（限速重试分页）
│   ├── store/           KlineStore / RealtimeStore / MetaStore / FinancialStore
│   └── jobs/            backfill / daily_maintenance / ws_collector
└── backtest/            回测引擎（策略层，第四期已完成）
    ├── indicators.py    MA / EMA / RSI / MACD / KDJ / ATR / BOLL
    ├── broker.py        撮合与账户
    ├── strategy.py      Strategy 基类 + Context
    ├── engine.py        回测引擎循环
    └── performance.py   绩效统计 + 权益曲线
└── factors/             因子库（策略层，第五期已完成）
    ├── registry.py      因子定义注册表 + 指纹
    ├── compute.py       因子计算（输入校验 + 引用 indicators / 滚动算子）
    ├── store.py         FactorStore（parquet 分区 + 惰性取数 + 原子写）
    └── factors.py       内置量价因子（import 即注册）
└── webui/               Web 查询后端（第六期，进行中）
    ├── app.py           create_app 工厂：三只读存储 + 生产挂 frontend/dist
    └── api.py           /api 只读端点（periods/coverage/klines/factors/factor-dirs/factor-values）
frontend/                前端（第六期）：Vite + React + antd + ECharts（K 线/因子浏览；行情终端风：红涨绿跌、深色报价头、左右分栏）
examples/
├── strategies/ma_cross.py   双均线示例策略
└── run_backtest.py          真实数据单标的 + 多标的回测
```

数据存储：`data/`（已 gitignore）
- `klines/` — K 线 Parquet，日线按 `year`、分钟按 `year/month` 分区，只存原始价
- `realtime/` — WS 快照，`date=YYYY-MM-DD` 分区
- `meta.db` — SQLite（WAL），coverage / 元数据 / 财务 / 报告

---

## 权限与数据深度说明

- **分钟 K 线**：当前套餐**已可用**，历史深度限**最近一年**（2026-08-30 实测）
- **实时行情 WS 推送**：当前套餐**无权限**；代码已实现并通过测试，待开通后可盘中启用（当日段 intraday 查询不受影响）
- 详见 [docs/sdk-notes.md](docs/sdk-notes.md)（SDK 实测记录：限流、异常、字段）

---

## 设计文档与进度

- 设计文档：[docs/superpowers/specs/2026-08-30-data-center-design.md](docs/superpowers/specs/2026-08-30-data-center-design.md)
- 实施计划：
  - [第一期 · K线缓存 + 历史回填](docs/superpowers/plans/2026-08-30-data-center-phase1.md) ✅
  - [第二期 · 复权 + 财务/元数据 + 校验 + 日终](docs/superpowers/plans/2026-08-30-data-center-phase2.md) ✅
  - [第三期 · WS 采集 + 盘中半可变层](docs/superpowers/plans/2026-08-30-data-center-phase3.md) ✅
  - [第四期 · 回测引擎 + 真实回填验证](docs/superpowers/plans/2026-08-30-backtest-phase4.md) ✅
  - [第五期 · 因子库](docs/superpowers/plans/2026-08-30-factors-phase5.md) ✅
  - [第六期 · Web 查询界面](docs/superpowers/plans/2026-08-31-webui-phase6.md) 🔄 进行中（后端完成，前端已可构建）
