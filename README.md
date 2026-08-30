# A 股回测数据中心

为 A 股回测系统构建的**本地优先、缺失回源、查到即存**的数据中心。数据源为 [TickFlow](https://tickflow.org)（已购买），提供官方 Python SDK。

- **本地优先**：所有查询先走本地存储（Parquet + SQLite），命中即零网络
- **查到即存**：缺口回源并落库，相同数据永不重复请求
- **断点续传**：历史回填中断后重跑同一命令即续传
- 当前已实现 **第一期**：K 线缓存（11 周期）+ 全市场历史回填

## 安装

```bash
# 1. 安装依赖（Python 3.11+）
uv sync

# 2. 配置 API Key（访问 https://tickflow.org 获取）
export TICKFLOW_API_KEY="your-api-key"
```

建议把 `export TICKFLOW_API_KEY=...` 写进 `~/.zshrc` 或 `~/.bashrc`。

## 快速上手

```python
from datacenter import DataCenter

dc = DataCenter()

# 查询 600000.SH（浦发银行）近 3 年日 K，自动回源并缓存
df = dc.get_klines("600000.SH", period="1d")
print(df.tail())

# 指定时间范围（毫秒时间戳）
import time
end_ms = int(time.time() * 1000)
df = dc.get_klines("002491.SZ", period="1d",
                   start_ms=end_ms - 15 * 86_400_000, end_ms=end_ms)
print(df)
```

第二次查询完全走缓存，零网络请求。

## 历史回填

```bash
# 全量：10 个周期 × 全市场（先粗后细，分钟级自动按套餐硬限制取最近 365 天）
uv run python scripts/backfill.py

# 只补指定周期
uv run python scripts/backfill.py --periods 1d,1w

# 调整速率档位（日线批量 60 次/分 = 1.0；分钟批量 30 次/分 = 0.5）
uv run python scripts/backfill.py --rate 0.5
```

中断后重跑同一命令即续传。

## 目录结构

```
stock/
├── pyproject.toml              # uv 管理；依赖：tickflow[all], duckdb, pandas, pyarrow
├── docs/
│   ├── sdk-notes.md            # SDK 实测记录（限流、异常、字段）
│   ├── openapi.json            # 接口字段参考
│   └── superpowers/
│       ├── specs/              # 设计文档
│       └── plans/              # 三期实施计划
├── src/datacenter/
│   ├── api.py                  # 门面 DataCenter（唯一入口）
│   ├── resolver.py             # CacheResolver（缓存命中/缺口决策）
│   ├── client/                 # TickFlowClient（SDK 薄封装：限速+重试+分页）
│   ├── store/                  # KlineStore(Parquet/DuckDB) + MetaStore(SQLite)
│   └── jobs/backfill.py        # 批量回填任务
├── scripts/
│   ├── backfill.py             # 回填 CLI
│   └── demo_kline.py           # 示例：查询单只股票日 K
├── data/                       # 运行时数据（已 gitignore）
└── tests/                      # pytest（--timeout=60）
```

## 存储布局

```
data/
├── klines/                     # Parquet，Hive 分区
│   ├── period=1d/year=2024/part-*.parquet
│   ├── period=1m/year=2025/month=08/part-*.parquet
│   └── ...
└── meta.db                     # SQLite（WAL 模式）
```

- **K 线列**：`symbol, timestamp(ms), open, high, low, close, volume, amount`，只存原始价（`adjust=none`）
- **分区**：日线及更粗按 `year`；分钟级按 `year/month`（Asia/Shanghai 时区）
- **去重语义**：同一 `(symbol, timestamp)` 后写胜出（靠文件名时间戳）
- **coverage**：`kline_coverage` 表记录每个 `(symbol, period)` 已解析区间，缺口判断依赖它

## 设计文档

- 设计文档：[docs/superpowers/specs/2026-08-30-data-center-design.md](docs/superpowers/specs/2026-08-30-data-center-design.md)
- 实施计划：
  - [第一期 · K线缓存 + 历史回填](docs/superpowers/plans/2026-08-30-data-center-phase1.md) ✅ 已完成
  - [第二期 · 复权 + 财务/元数据缓存 + 数据校验 + 日终维护](docs/superpowers/plans/2026-08-30-data-center-phase2.md) ⏳ 待做
  - [第三期 · WS 实时采集 + 盘中半可变层](docs/superpowers/plans/2026-08-30-data-center-phase3.md) ⏸ 暂缓

## 分期说明

- **第一期（已完成）**：K 线缓存（Parquet/DuckDB）+ 回填任务（批量接口、断点续传、速率自适应）
- **第二期（待做）**：本地复权计算、财务/标的元数据/标的池缓存、数据校验（连续性/抽样比对/交叉校验）、日终维护任务
- **第三期（暂缓）**：WebSocket 实时行情采集 + 盘中半可变层。实时行情整体暂缓，优先回测能力
