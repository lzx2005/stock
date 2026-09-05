# 策略模块 · 设计文档

日期：2026-09-01
状态：已实现（第七期）

## 1. 背景与目标

用户对一个策略**不断优化**（条件不断叠加），需要能回答："这次改动比原来强吗？"。已有模块覆盖了数据（行情/数据中心）、信号（因子库）、验证（回测引擎），但没有**策略本身的管理**——每次回测结果散落在 `reports/` 目录，无法横向比较不同版本。

目标：在行情模块、因子模块之后加一层**策略模块**，统一管理：**策略名称、策略方案、回测记录、回测结果**，并建立**策略列表 + 版本**概念：

- 每次回测要么选一个已测策略（版本号递增），要么新建策略（=v1）；
- 每个新版本的回测记录自动与 **v1（原始版）** 与 **上一版** 对比，判定"有没有进度"；
- 生成的 PDF 与记录都带版本归属，可随时回溯任意版本的方案与结果。

### 产品形态（用户确认）

- **不做条件选股**（沿用一期边界）：策略模块只负责"存储 + 版本 + 对比"，结论仍落到回测 + 同花顺一句话条件。
- **本期范围**：后端存储 + CLI + 回测专家 skill 集成。Web 策略 tab 留待后续（照因子浏览 pattern 补，`list_strategies()` 已返回可 JSON 序列化 dict，供 `/api/strategies` 复用）。
- 对比基准：新版本**同时对比 v1 和上一版**。

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 存储方案 | **目录式 JSON**（镜像 `src/factors/` 的 parquet 分区 + 原子写风格），零新依赖，纯文件系统 |
| 目录布局 | `data/strategies/<整数id>/strategy.json + versions/<N>/`；id 单调递增、删除不重用 |
| id 分配 | `manifest.json` 只存 `next_id`；列表走扫描（对齐 `FactorStore.list_stored()`），避免索引/目录双源漂移 |
| 版本语义 | 每次 record = 新版本（N+1）；v1 为原始版 |
| 结果记录 | 复制 skill 产物进版本目录（results.json / equity.csv / report.md / strategy_v<N>.py / backtest_meta.json），PDF/png 在版本目录生成 |
| **边车文件** | `backtest_meta.json`（复权口径/成本模型/策略类/参数/区间）——results.json 缺这些决定参数，没有它无法做可比性检查 |
| 对比逻辑 | 纯函数（`src/strategy/compare.py`，无 I/O），单测友好 |
| 判定规则 | 主指标 4 项（total_return / 超额收益 / max_drawdown / sharpe）：无一项变差且（≥2 项变好 或 总收益变好）= **进步**；总收益变差 或 变差项 ≥2 = **退步**；否则 **部分改善** |
| 可比性纪律 | symbols/period/复权口径/区间/初始资金/成本模型(6字段) 全等才可比；策略 params 不同**不**阻断（那正是被测对象） |
| 与 skill 集成 | record 登记版本 + build_report 在版本目录出含"七、版本对比"章节的 PDF；老 reports/ 目录无 comparison.json 时保持原 6 章，向后兼容 |
| 接线 | **不动 `src/datacenter/api.py`**（StrategyStore 纯文件系统）；`pyproject.toml` packages 加 `src/strategy` |

## 3. 整体架构

```
回测专家 skill / CLI / （后续）Web 策略 tab
        │  StrategyStore.import_version(report_dir) / list_strategies() / compare...
        ▼
┌─ StrategyStore（src/strategy/store.py）────────────────┐
│  目录式 JSON：create / list / rename / delete /         │
│  import_version（复制产物→写 version.json→自动对比）     │
│  原子写：tempfile.mkstemp + os.replace                 │
└──────────────┬────────────────────────────────────────┘
        │  read/write JSON
        ▼
   data/strategies/
   ├── manifest.json              # {"next_id": N}
   └── <id>/
       ├── strategy.json          # 名称/方案/created/updated/latest_version
       └── versions/<N>/
           ├── version.json       # 版本元数据 + 回测决定参数 + 结果摘要
           ├── results.json / equity.csv / report.md / strategy_v<N>.py
           ├── backtest_meta.json # 边车（复权/成本模型/参数/区间）
           ├── comparison.json    # v>=2 才有（vs v1 + vs 上一版）
           └── 回测报告.pdf / equity_curve.png   # build_report 在版本目录生成

┌─ compare.py（纯函数）──────────────────────────────────┐
│  comparable / metric_delta / excess_return /            │
│  judge_verdict / compare_versions / build_comparison    │
└─────────────────────────────────────────────────────────┘
```

## 4. 数据模型

### `data/strategies/<id>/strategy.json`
```json
{ "id": 1, "name": "双均线金叉+ATR止损", "description": "用户需求原话",
  "created_at_ms": 1753823460000, "updated_at_ms": 1753910000000,
  "latest_version": 2 }
```

### `versions/<N>/version.json`
```json
{ "version": 2, "strategy_id": 1, "strategy_name": "双均线金叉+ATR止损",
  "created_at_ms": 1753910000000, "strategy_file": "strategy_v2.py",
  "strategy_class": "MaCrossAtrStop", "params": {"fast":5,"slow":20,"atr_n":14,"stop_atr_k":2},
  "change_note": "新增 ATR 止损",
  "backtest": {"symbols":["600519.SH"],"period":"1d","start_ms":1693267200000,
    "end_ms":1756252800000,"start":"2023-08-29","end":"2026-08-28",
    "initial_cash":1000000,"adjust":"forward",
    "broker":{"commission":0.0003,"min_commission":5.0,"stamp_tax":0.0005,
              "slippage":0.0,"lot_size":100,"t_plus_1":true}},
  "results": {"metrics":{8 项},"benchmark":{"name":"买入持有","total_return":-0.22},
              "excess_return":0.17} }
```

### `versions/<N>/comparison.json`（v≥2）
```json
{ "strategy_id": 1, "version": 2, "created_at_ms": ...,
  "comparable": true, "note": "", "primary": ["total_return","excess_return","max_drawdown","sharpe"],
  "vs_v1":  { "version": 1, "comparable": true, "verdict": "progress",
              "metrics_delta": {"total_return":{"old":-0.05,"new":-0.02,"delta":0.03,"better":true}, ...} },
  "vs_prev": { "...同构..." } }
```
- `better` 方向：total_return / excess_return / sharpe / win_rate / profit_loss_ratio / final_equity **升为好**；max_drawdown **降为好**；trade_count **无方向**。
- 不可比 → `comparable:false` + `note`（列出哪些维度不一致），无 delta/verdict。
- 特判：`profit_loss_ratio` 全赢 = `inf`（含 inf 时 delta 置 None，方向照判——inf 被打破记退步）。

### 边车 `backtest_meta.json`（skill Step4 写入 scratch，record 读取）
```json
{ "strategy_class": "...", "params": {...}, "change_note": "...",
  "adjust": "forward",
  "broker": {"commission":0.0003,"min_commission":5.0,"stamp_tax":0.0005,
             "slippage":0.0,"lot_size":100,"t_plus_1":true},
  "start_ms": ..., "end_ms": ... }
```
symbols/period/start/end/initial_cash 从 results.json 取；start_ms/end_ms 补进边车。

## 5. 版本对比语义

- 新版本 record 时自动同时对比 **v1** 与 **上一版**，写 comparison.json + 追加 report.md 对比节。
- 判定用主指标 4 项；`better` 方向见 §4。
- 可比性：仅策略 params 不同时可比（那是被测对象）；改标的/区间/成本模型 → 不可比，PDF/report.md 标注原因不下结论。
- 建议：同一策略的迭代固定标的/区间/成本模型；换标的/区间另建策略。

## 6. 与既有模块接线

- 新增 `src/strategy/`（errors / store / compare），不依赖 DataCenter。
- `pyproject.toml` packages 加 `"src/strategy"`。
- 回测专家 skill：产出目录说明、Step1 选策略、Step4 写 backtest_meta.json、Step5 改 record + 版本目录出 PDF、"版本对比语义"小节。
- `build_report.py`：`build_pdf()` 末尾加可选"七、版本对比"章节（读 comparison.json；缺失/损坏静默跳过，向后兼容）。
- CLI `scripts/strategy_cli.py`：create / list / show / versions / show-version / record / compare / rename / delete。

## 7. 验收

- 新增 33 测试：store CRUD/版本递增/原子写/产物复制、compare 可比性/方向/inf 特判/判定三态、CLI 冒烟、build_report 对比章节渲染。
- 全量 `.venv/bin/python -m pytest tests/` → 200 passed。
- 端到端：`create` → `record`（v1）→ 改条件再 `record`（v2）→ `list` 见进度判定 → `build_report.py` 版本目录出含"七、版本对比"的 PDF。
