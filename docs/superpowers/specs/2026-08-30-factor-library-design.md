# 因子库 · 设计文档

日期：2026-08-30
状态：待用户审阅

## 1. 背景与目标

回测引擎（`src/backtest/`）在策略 `init`/`on_bar` 阶段反复计算技术指标（`backtest.indicators` 的 ma/rsi/macd 等）。每次跑回测都从头重算一遍：算力浪费，且同一指标在不同策略/脚本里的口径可能漂移。

目标：建立一个**因子库**，统一管理因子**定义**与**计算值**，回测复用同一份值——**算一次，存起来，以后直接用**。

核心模式（与数据中心一致）：**本地优先，缺失计算，查到即存**——查询因子值先读本地存储，没有（或区间缺失）才从数据中心取 K 线现算并落库，相同计算永不重复执行。

### 工作流边界（用户确认）

**不做条件选股**——同花顺的一句话/几句话选股已足够强，选股能力不在本系统范围内。本系统只做**回测模拟验证**：

1. Claude 提出候选条件（如"5 日线上穿 20 日线 且 量比 > 1.5"）
2. 回测量化该条件对收益的贡献（能验证想法的强弱）
3. 条件验证有效后，**转述为同花顺一句话选股**去筛股
4. 用户拿到筛出的股票自行买入（手动交易，不做自动下单）

因此因子的设计语义是：**可命名、可转述为同花顺条件句的原子条件**（如 `ma5`、`vol_ratio`、`mom5`），而不是黑盒组合信号。因子库提供这些原子的"定义 + 值"，回测负责验证哪些原子/组合利于收益。

非目标（本期不做）：
- 基本面因子（ROE/PE/营收增速等）——registry 架构预留，后续迭代接入 DataCenter 财务数据
- 横截面因子（rank/z-score/中性化、多因子打分选股）——同上，架构预留
- 分钟级因子——storage 层按 period 通用，本期只登记 1d
- 因子挖掘/自动搜索（alphalens 式）——本期只做"定义 + 存储 + 复用"的底座

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 因子范围 | 第一期**量价技术因子**：ma/ema/rsi/macd/kdj/atr/boll + **条件因子 vol_ratio（量比）/mom（动量）/bias（乖离率）**——后三者直接对应同花顺一句话选股的常见条件（量比>1.5、N日涨幅、乖离） |
| 取数方式 | **惰性按需 + 缓存**：策略声明因子，FactorStore 有值直接读、没有现算再存（复刻 `datacenter.CacheResolver` 的 fetch-through 模式） |
| 存储方案 | **独立 `src/factors/` 包 + parquet 分区存储**（镜像 KlineStore 风格），零新依赖 |
| 一期验收 | **改造双均线走因子库**：MaCross 从 FactorStore 取 MA5/MA20，跑通"定义→计算→存储→复用"整条链 |
| 复权口径 | 因子值按 **forward（前复权）** 计算并存储，与回测引擎 `adjust="forward"` 一致 |
| 一致性保证 | 缓存指纹 = `sha1(name\|params\|version\|adjust)`——改参数/改公式/改复权口径自动换 key 重算，旧值保留不误删 |
| 产品边界 | **不做条件选股**（同花顺一句话选股承担）；回测产出 = 验证哪些条件利于收益；用户拿条件去同花顺筛股、自行买入（见 §1 工作流边界） |

复权口径的理由：回测引擎预取 K 线用前复权，因子服务回测就必须同口径，否则除权跳空会造成 MA 交叉假信号。代价是除权日后历史因子值整体漂移、覆盖校验检测不到——用 `FactorStore.refresh()` 手动重算兜底（见 §7）。

## 3. 整体架构

```
策略代码（如 MaCross）
        │  FactorStore.get(symbol, name, params, period, start, end)
        ▼
┌─ FactorStore（src/factors/store.py）──────────────┐
│  get(): 指纹定位 → 读 parquet → 区间覆盖校验       │
│         覆盖 → 切片返回                            │
│         缺口 → DataCenter 取 K 线 → compute → 合并写回 │
└──────────────┬────────────────────────────────────┘
        ▲      │  read/write parquet        ▲  get_klines(adjust="forward")
        │      ▼                           │
   data/factors/<指纹>/              DataCenter（数据中心门面）
   ├── factor.json                  └─ 已有设施，只读
   └── symbol=*/period=*/part.parquet
        ▲
        │  apply_factor(def, df)
   src/factors/compute.py ──调用──> backtest.indicators（已有，零重复实现）
```

三块职责单一、可独立测试：`registry` 管定义、`compute` 管计算、`store` 管持久化与复用。

## 4. 因子定义注册表（registry.py）

```python
@dataclass(frozen=True)
class FactorDefinition:
    name: str            # "ma"
    category: str        # "price-volume"（一期全量）
    period: str          # "1d"（一期全量）
    version: int         # 公式/口径变更时 +1
    inputs: tuple[str, ...]  # 需要的 K 线列，如 ("close",) / ("high","low","close")
    fn: Callable         # (df: DataFrame, **params) -> Series（值按 df.index 对齐）
    default_params: dict
    doc: str
```

- 注册：`@register_factor(def)` 或 `register_factor(name, category=..., ...)`，登记到模块级 `REGISTRY`。
- 解析：`get_factor(name, params)` 合并默认参数、校验未知参数、按规范化排序后的 params 计算指纹。
- 指纹：`sha1(f"{name}|{sorted_params_json}|{version}|{adjust}")[:16]`——定义快照的数字签名。
- **因果性约束（写入 docstring 与校验）**：一期因子必须是"bar i 的值只依赖 ≤i 的数据"的因果指标（rolling/ewm/shift 类）。这是回测无前视与"整段预取、按 ts 索引"可行的根基。
- `list_factors()`：列出已注册定义（供预热脚本、查看器使用）。

## 5. 计算层（compute.py）

`apply_factor(def: FactorDefinition, df: DataFrame) -> pd.Series`：
- 校验 df 含 `def.inputs` 所需列；缺列抛 `FactorInputError`。
- 调用 `def.fn(df, **params)` 得 Series，值按 df 索引（K 线 timestamp，毫秒 int）对齐。
- 内置因子**只做注册，不重复实现公式**——`fn` 直接引用 `backtest.indicators`，**条件因子（vol_ratio/mom/bias）用 pandas 原生滚动算子**（同样因果、零新依赖）：
  - `ma(n)` → `indicators.ma(df["close"], n)`
  - `ema(n)` / `rsi(n)` / `atr(n)` → 对应 indicators
  - `macd(fast, slow, signal)` → `indicators.macd(...)`，按输出列拆分为独立因子
  - `kdj(n)` → `indicators.kdj(...)`，同理 `kdj_k/kdj_d/kdj_j`
  - `boll(n, k)` → `indicators.boll(...)`，`boll_mid/boll_up/boll_low`
  - `vol_ratio(n=5)` → `volume / volume.rolling(n).mean()`（量比：当日量/近 n 日均量；同花顺"量比>1.5"即取 n 日内常用口径）
  - `mom(n=5)` → `close.pct_change(n)`（N 日动量/涨幅；同花顺"N日涨幅"）
  - `bias(n=20)` → `(close - ma(close, n)) / ma(close, n)`（乖离率：价离均线的百分比偏离；同花顺"乖离率"）
- 决策：多输出指标（macd/kdj/boll）注册为**每输出一个因子**（`macd_hist`、`kdj_j` 各自独立名），便于按名取单列；各自 `default_params` 相同。
- **条件表达映射**：每个因子的 doc 里写清"同花顺条件句"怎么写（如 `ma`：`MA5>MA20`；`vol_ratio`：`量比>1.5`；`mom`：`5日涨幅>10%`），让"回测验证 → 转述选股"无缝衔接。

## 6. 存储与取数（store.py）

### 6.1 布局（镜像 KlineStore 的 parquet 分区风格）

```
data/factors/<指纹>/
├── factor.json              # 定义快照：name/params/version/adjust/category/period/doc
└── symbol=600000.SH/
    └── period=1d/
        └── part.parquet     # columns: [timestamp, value]（timestamp 毫秒 int）
```

- 每 `(指纹, symbol, period)` 一个 parquet，单列因子值。小文件、pandas 直接读。
- 写纪律：**整段覆盖写**（先算全窗口，合并旧区间的保留值，一次写入）避免频繁追加；写临时文件 + 原子 rename（沿用 KlineStore 的原子写模式）。
- 存储根目录构造参数 `FactorStore(dc, root="data/factors")`。

### 6.2 取数

`get(symbol, name, params, period, start_ms, end_ms) -> pd.Series`（索引 = timestamp，值 = 因子值）：
1. `get_factor(name, params)` 解析并计算指纹。
2. 读 `part.parquet`，取存储覆盖区间 `[lo, hi]`。
3. `[lo, hi]` ⊇ `[start_ms, end_ms]` → 按区间切片返回。
4. 否则缺口（含区间从未算过）→ 按缺口从 `dc.get_klines` 取 K 线 → 排序去重 → `apply_factor` → 与已存区间**按 timestamp 求并集合并**（重叠区以已存为准，只补缺口）→ 原子写回 → 返回请求区间的切片。

**尾部缺口的 lookback seed**（因子定义 `lookback` 字段）：滚动类因子在缺口内算不满窗，缺口起始的 n-1 根会出 NaN；若直接落盘会被覆盖快路径永久喂养。因此**尾缺口**补算时把取数起点前移 `lookback` 根（`fetch_from = max(start_ms, hi+1-lookback)`），取 K 线算完丢弃 seed 区（`tail.loc[hi+1:end_ms]`）再合并。`lookback` 是**取数优化，不进缓存指纹、不进 factor.json**（因子值不受其影响，旧缓存不失效）；ewm 类因子（ema/macd_hist）无窗口期，`lookback=0`；rolling 类（ma/rsi/atr/kdj/boll/vol_ratio/mom/bias）取 `lambda p: p["n"]`。

**等价性边界（如实声明）**：对**平移不变滚动因子**（ma/boll/vol_ratio/mom/bias，值只依赖最近 n 根 K 线），seed 后缺口起始即满窗，尾部缺口值与整段现算**逐根相等**。对**递推平滑因子**（rsi/kdj_j/atr，Wilder/ewm 递归，值依赖全部历史），seed 使递归从头收敛，缺口起始附近是收敛近似而非精确值（rsi 缺口边界偏差可达数十点，随远离边界指数衰减）。这是增量"活计算"的固有语义：增量消费方（定期 warm、窗口后移）得到的是种子收敛值，严格优于 NaN；需要精确整段重算用 `refresh()`。单次全窗 init 无缺口，恒等于现算。

要点：
- 补算只算缺口，不重算已覆盖区间——`get_klines` 请求区间 = 缺口区间 ± 前移的 lookback seed，最小化数据源请求（seed 是 K 线、由 KlineStore 缓存吸收，不算重复补算）。
- 因子值在**窗口头部**的窗口期 NaN（如 ma20 前 19 根）如实保留，与现算一致——只覆盖缺口起始之后；头缺口/整窗填充不做 seed（请求窗口之前的 warmup 是真实 warmup）。

### 6.3 批量预热

`warm(symbols, factors, period, start_ms, end_ms)`：对每标×因子循环 `get()`，可选 `show_progress`。一期作为脚本入口 `scripts/factor_warm.py` 提供，为将来全市场预计算留位（本期验收用不上，但接口与入口先就位）。

## 7. 缓存语义、失效与刷新

| 场景 | 行为 |
|---|---|
| 参数变更 | 指纹变 → 新目录，自动重算；旧值保留不误删 |
| 公式/口径变更（version bump） | 同上 |
| 新 K 线入库（尾部数据更新） | 区间覆盖校验检测尾部缺口 → 惰性补算 |
| **除权事件（前复权基准日漂移）** | 覆盖校验**检测不到**（区间没缺、值已漂移）→ `refresh()` 手动重算 |
| 用户主动作废 | `drop(name, params, adjust=None)` 删指纹目录 |

`refresh(symbol, name, params, period, start, end)`：忽略缓存，强制用当前 K 线全量重算并覆盖写。一期由用户/脚本手动触发（如每交易日日终维护后跑一次 `factor_refresh.py`）；是否接入 `jobs/daily_maintenance.py` 留到后续迭代。

## 8. 策略消费：双均线改造（一期验收）

`examples/strategies/ma_cross.py` 改造：

```python
class MaCross(Strategy):
    def __init__(self, short=5, long=20, fs=None):
        self.short, self.long = short, long
        self.fs = fs                      # 注入 FactorStore（runner 构造）

    def init(self, ctx):
        # 整段预取因子序列（因果指标无前视，init 用全量历史即可）
        self.ma_s, self.ma_l = {}, {}
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if h.empty:
                continue
            ts = h["timestamp"]
            self.ma_s[symbol] = self.fs.get(symbol, "ma", {"n": self.short}, "1d", ts.min(), ts.max())
            self.ma_l[symbol] = self.fs.get(symbol, "ma", {"n": self.long}, "1d", ts.min(), ts.max())

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if len(h) < self.long + 1:
                continue                      # 慢线窗口不足，与现算版一致
            t = ctx.now
            s, l = self.ma_s[symbol].loc[t], self.ma_l[symbol].loc[t]
            s_prev = self.ma_s[symbol].loc[ctx.history(symbol)["timestamp"].iloc[-2]]
            l_prev = self.ma_l[symbol].loc[ctx.history(symbol)["timestamp"].iloc[-2]]
            held = symbol in ctx.positions
            if s_prev <= l_prev and s > l:    # 金叉
                ctx.buy(symbol)
            elif held and s_prev >= l_prev and s < l:  # 死叉
                ctx.sell(symbol)
```

- **规则逻辑零改动**，只换因子来源（现算 → FactorStore 取数）。
- 正确性由 golden 对拍保证：改造后跑同一窗口，逐笔交易、权益曲线与现算版**完全一致**（见 §10）。
- `examples/run_backtest.py` 构造 `MaCross(5, 20, fs=FactorStore(dc))`；首跑落盘，二次/重启后命中缓存（可在 `data/factors/` 看到落盘文件）。

## 9. 错误处理

| 异常 | 触发 | 处理 |
|---|---|---|
| `FactorInputError` | df 缺因子所需列 | 计算前抛，明确列名 |
| `FactorUnknownError` | `get_factor` 未注册的 name | 抛，提示 `list_factors()` |
| `FactorParamError` | 未知/非法参数 | 抛，提示合法参数 |
| 数据源异常 | `dc.get_klines` 抛 `DataCenterError` | 原样透传（与回测引擎一致），缓存层不吞 |

## 10. 测试策略

沿用 `tests/conftest.py` 的 FakeTickFlow/make_kline_df 假数据；因子库测试不依赖真实数据源。

- `tests/test_factor_registry.py`：注册/解析/默认参数合并/未知参数报错/**指纹稳定性**（同定义同指纹；改 name/params/version/adjust 各变指纹）
- `tests/test_factor_compute.py`：指标类因子与 `backtest.indicators` **逐值对拍**（`apply_factor(ma, df) == indicators.ma(df, n)`），确认零重复实现；条件因子（vol_ratio/mom/bias）与**手算滚动值**对拍（`volume.rolling(n).mean()` 等）；多输出因子（macd/kdj/boll）按输出列拆分为独立因子且值一致
- `tests/test_factor_store.py`：
  - 首次 `get` 计算 + 落盘；二次 `get` 命中缓存**不触发** `dc.get_klines`（用计数代理包 dc 断言调用次数）
  - 区间缺口：先取小区间，再取更大区间 → 只补尾部缺口，不重算已覆盖区
  - version bump → 新指纹重算、旧目录保留
  - **无前视断言**：因子值在 bar i 与"只用 ≤i 数据现算"完全一致（因果性）
  - 原子写：写坏场景不残留半文件（可选）
- `tests/test_ma_cross_factors.py`：**golden 对拍**——`MaCross(fs=FactorStore(...))` vs 现算版 `MaCross()`，同一窗口回测，逐笔交易与权益曲线完全一致

## 11. 项目结构

```
src/factors/
├── __init__.py      # 导出 FactorStore / register_factor / get_factor / list_factors / 异常
├── registry.py      # FactorDefinition + REGISTRY + 指纹
├── compute.py       # apply_factor + 输入校验
├── store.py         # FactorStore（parquet 读写 + 区间合并 + 原子写）+ refresh/drop/warm
└── factors.py       # 内置量价因子注册（import 即注册）
scripts/
└── factor_warm.py   # 批量预热入口（本期就位，验收用不到）
docs/superpowers/plans/2026-08-30-factors-phase5.md   # 实施计划（checkbox，Commit 步不勾）
tests/
├── test_factor_registry.py
├── test_factor_compute.py
├── test_factor_store.py
└── test_ma_cross_factors.py
```

## 12. 实施分期

- **P1 底座**：registry + compute + 内置因子注册（含条件因子 vol_ratio/mom/bias）+ 单测（指标对拍 indicators、条件因子对拍手算滚动值）
- **P2 存储**：store + 区间合并 + 原子写 + 惰性取数 + 单测（命中/补缺口/版本/无前视）
- **P3 消费**：MaCross 改造 + run_backtest 走因子库 + golden 对拍 + 真实数据 smoke
- **P4 收尾**：`scripts/factor_warm.py`、README 补充、全量回归、计划 checkbox 入库（Commit 步按用户规则保持未勾）

后续迭代方向（本期不做，架构已预留）：多条件组合策略示例（如"双均线金叉 且 量比>1.5"直接验证用户给的条件句）、基本面因子接入、横截面因子与多因子打分。每验证一个有效条件，产出即可转述为同花顺一句话选股交给用户。
