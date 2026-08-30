# A 股回测数据中心 · 设计文档

日期：2026-08-30
状态：待用户审阅

## 1. 背景与目标

为 A 股回测系统建设一个**稳定、高速、准确**的本地数据中心。数据源为 TickFlow（已购买，含 REST 历史接口与 WebSocket 实时接口，官方提供 Python SDK `tickflow[all]>=0.1.17`，API Key 经环境变量 `TICKFLOW_API_KEY` 配置）。

核心模式：**本地优先，缺失回源，查到即存**——所有查询先查本地数据库，本地没有则调用远程接口并落库，相同数据永不重复请求。在此基础上预拉取全市场过去 3 年的全部数据。

非目标（本期不做）：
- 回测引擎本身（数据中心是它的数据依赖）
- 实盘交易对接
- 多机分布式部署

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 数据范围 | 全部：K 线（1m/5m/10m/15m/30m/60m/1d/1w/1M/1Q/1Y 共 11 周期）、五档 depth、实时 quotes、5 张财务表、除权因子、标的元数据、标的池 |
| 预拉取 | 全市场（5555 只 A 股）日线级（1d/1w/1M/1Q/1Y）× 3 年；分钟级（1m/5m/15m/30m/60m）× 最近 365 天（套餐硬限制，之后靠日终维护每日滚动积累）。**10m 不在套餐周期内**，需要时由 5m 本地聚合 |

### 套餐限流规格（2026-08-30 探测+用户确认）

| 接口 | 限流 |
|---|---|
| 日线 K 线 | 批量 60 次/分 × 200 标的；按只 120 次/分 |
| 分钟 K 线 | 批量 30 次/分 × 100 标的；按只 60 次/分；单次最多 5000 条；仅最近 365 天 |
| 除权因子 | 60 次/分 × 200 标的 |
| 实时行情 | 120 次/分 × 100 标的；标的池 60 次/分 |
| 日内分时 | 30 次/分 |
| 五档深度 | 批量 30 次/分 × 100 标的；按只 60 次/分 |

其他实测行为：非法 symbol **不抛异常**，返回空 DataFrame；SDK 异常类层次完整（`tickflow._exceptions.RateLimitError/APIError/...`），限流异常 message 含建议等待毫秒数。
| 使用形态 | **库模式**：Python 包，回测引擎直接 import，返回 pandas DataFrame |
| 数据库 | **DuckDB + Parquet**（K 线/行情大表）+ **SQLite**（财务/元数据/缓存状态/任务进度），零服务进程 |
| 复权 | 本地只存**原始价（adjust=none）+ 除权因子表**，复权在读取时本地计算 |
| 远程客户端 | 基于官方 `tickflow` SDK 薄封装，不手写 REST |

复权决策的理由：前复权价格以最新收盘价为基准，每天变化；若存储复权后数据，每次除权日后全部历史缓存失效。存原始价 + 因子表（很小），读取时用 numpy 向量运算复权，零成本且永远有效。

## 3. 整体架构

```
回测引擎 / 策略代码
        │  import，拿 pandas DataFrame
        ▼
┌─ DataCenter（门面 API）──────────────────────────┐
│  get_klines(symbol, period, start, end, adjust)   │
│  get_quotes / get_financials / get_instruments …  │
└──────────────────┬───────────────────────────────┘
                   ▼
        CacheResolver（缓存解析器）
        · 算出本地已覆盖的时间区间
        · 命中 → 直接读本地
        · 缺口 → 调远程 → 落库 → 返回
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
    LocalStore           TickFlowClient
    · Parquet: K线       （官方 SDK 薄封装：
    · SQLite: 财务/        限速/重试/统一异常）
      元数据/覆盖区间/            │
      任务进度             api.tickflow.org
        ▲                     ▲
        │                     │
   BackfillJob          WS 采集进程（第二阶段）
   （3 年历史回填，       （实时行情落库，
    断点续传）             独立进程）
```

分层职责：

1. **门面（api.py）**：统一入口，回测引擎唯一接触点，永远不直接碰 TickFlowClient
2. **解析器（resolver.py）**：缓存逻辑的唯一决策者，判断命中/缺口/回源
3. **存储（store/）**：ParquetStore（K 线读写）+ MetaStore（SQLite 读写）
4. **客户端（client/）**：官方 SDK 的薄封装，只加限速、重试、异常归一化

## 4. 缓存语义

数据按可变性分三级，"查过就存"不一刀切：

| 级别 | 数据 | 策略 |
|---|---|---|
| **不可变** | 已收盘的历史 K 线、财务表、除权因子、标的元数据 | 永久缓存：查过即存，永不回源 |
| **半可变** | 当日未收盘 K 线 | 盘中查询带 TTL（分钟级）或穿透；收盘后由日终任务固化为不可变 |
| **实时快照** | quotes / depth | 不进"缓存即真相"体系，查询默认穿透；WS 采集数据落独立 realtime 表供回放复盘 |

## 5. 存储布局

```
data/
├── klines/                                # Parquet，Hive 分区
│   ├── period=1d/year=2024/part-0.parquet
│   ├── period=1m/year=2025/month=08/part-*.parquet
│   └── ...
├── realtime/                              # WS 落库（第二阶段）
└── meta.db                                # SQLite（WAL 模式）
```

### 5.1 Parquet 分区规则

- 日线及更粗周期（1d/1w/1M/1Q/1Y）：`period/year` 分区
- 分钟级（1m~60m）：`period/year/month` 分区
- 单文件目标 128MB~1GB；1m 线一个月全市场约 300MB 原始 / 压缩后约 80MB，单文件合适
- 查询靠分区裁剪 + 列裁剪："600000.SH 近 3 年日线"只读 3 个小文件的必要列

### 5.2 SQLite 表（meta.db）

| 表 | 内容 |
|---|---|
| `instruments` | 标的元数据：代码、名称、交易所、上市日期、类型 |
| `ex_factors` | 除权因子：(symbol, ex_date, factor, …) |
| `fin_balance` / `fin_cashflow` / `fin_income` / `fin_metrics` / `fin_shares` | 5 张财务表，字段直接映射 API schema |
| `universes` / `universe_members` | 标的池及其成员 |
| `kline_coverage` | **解析器核心**：每个 (symbol, period) 本地已覆盖的连续时间区间 [start, end]，判断缺口靠它，避免每次扫描 Parquet 元数据 |
| `sync_jobs` | 回填任务进度：每个 symbol×period 的状态、已拉取时间点、重试次数（断点续传） |
| `job_reports` | 每次回填/维护任务的报告：拉取行数、缺口数、校验结果 |

### 5.3 写入纪律

- Parquet 写入三步：**写临时文件 → 原子 rename → 更新 kline_coverage**，任一步失败不留脏数据
- SQLite 开 WAL：回测只读连接与写入互不阻塞
- **单写者原则**：所有写入（回填、日终、WS 落库）各自独立进程/任务串行执行，并发只发生在网络请求侧

## 6. 历史回填（Backfill）

### 6.1 拉取顺序

1. 全市场 `instruments`（标的清单）
2. K 线从粗到细：1d → 1w/1M/1Q/1Y → 60m → 30m → 15m → 10m → 5m → 1m
   - 先粗后细：日线拉完（几分钟）系统即可做日线级回测，分钟线后台慢灌
3. 除权因子、财务表、标的池

### 6.2 执行机制

- 单次单标的最多 10000 根 K 线：3 年 1m 线约 18 万根/股 → 每股约 18 次分页请求；优先用 SDK 的 `klines.batch` 批量接口减少请求数
- **可配置令牌桶限速**：文档未注明限流规则，初始保守 10 req/s；收到限流响应自动指数退避并降速
- **断点续传**：每完成一个 symbol×period 提交 `sync_jobs`；中断重启后从进度恢复，已写入分区靠 `kline_coverage` 跳过
- **并发**：asyncio 8~16 路并发请求；写入单线程串行（网络是瓶颈，写入不是）
- **耗时估算**：全市场 5000 股 × 11 周期，总计约 5~8 万次请求，10 req/s 下约 2~3 小时

### 6.3 数据校验（"准确"的保障）

回填完成后执行：
1. **连续性检查**：每个 symbol 的 K 线时间戳对照交易日历，有洞补拉
2. **抽样比对**：随机抽 1% symbol 重新回源逐值比对
3. **交叉校验**：1m 聚合结果 vs 1d（成交量/成交额在容差内）

## 7. 实时与日终维护

### 7.1 WS 采集进程（第二阶段，独立进程）

- 订阅 symbol 列表（全市场或标的池），推送 → 内存缓冲 → 按 N 秒或 M 条批量落 `realtime/` Parquet（按日期分区）
- 断线自动重连 + 重订阅；重连缺口收盘后由日终任务用 REST 补齐
- 盘中作为"当日 K 线真相源"：当日 1m K 线由 WS 数据实时聚合，填充半可变层
- **待验证**：官方 SDK 是否暴露 WebSocket 接口（skill 文档未提及）；若无则按服务商 WS 文档直连。实现第一阶段开始前确认

### 7.2 日终维护任务（每交易日收盘后，cron 触发）

1. 拉当日全市场日 K，追加 `period=1d` 分区，固化当日数据为不可变
2. 更新除权因子表（复权在读取时计算，历史数据**无需重写**）
3. 分钟线日终核对：WS 聚合当日分钟线 vs REST 官方分钟线，不一致以 REST 为准覆盖
4. 更新 `instruments`（新股/退市）、`kline_coverage`

效果：数据中心自我维持，每晚跑一次维护即可保证历史永远完整。

## 8. 错误处理

- TickFlowClient 统一分类：限流 → 指数退避降速；5xx → 重试 3 次；4xx 参数错误 → 直接抛出不重试；所有重试带 jitter
- 门面 API 回源失败时：本地有部分数据 → 返回本地数据 + 警告标记缺口区间；本地完全没有 → 抛 `DataUnavailableError`
- **绝不允许静默返回残缺数据**——回测中残缺数据 = 错误结论，这是"准确"的底线

## 9. 测试策略

| 对象 | 方法 |
|---|---|
| TickFlowClient | 录制响应做契约测试（fixture），不依赖真实网络 |
| CacheResolver | 单元测试：命中 / 全缺口 / 部分缺口 / 跨分区拼接 四种场景（逻辑最密的组件） |
| 复权计算 | 用真实除权案例（如 600000 历史分红）手算对拍 |
| 端到端 | 小数据集（10 股 × 1 个月）跑通"回源 → 落库 → 再查走缓存"全流程 |

## 10. 项目结构

```
stock/
├── pyproject.toml              # uv 管理；依赖：tickflow[all], duckdb, pandas, pyarrow, httpx(如需), pytest
├── docs/
│   ├── openapi.json            # 接口字段参考
│   └── superpowers/specs/      # 本文档
├── src/datacenter/
│   ├── api.py                  # 门面 DataCenter
│   ├── resolver.py             # CacheResolver
│   ├── client/                 # TickFlowClient（SDK 薄封装 + 限速重试）
│   ├── store/                  # ParquetStore + MetaStore(SQLite)
│   ├── adjust.py               # 复权计算
│   ├── jobs/                   # backfill / daily_maintenance / ws_collector
│   └── quality.py              # 数据校验
├── data/                       # 运行时数据（gitignore）
└── tests/
```

## 11. 实施分期

- **第一期**：项目骨架 + TickFlowClient 封装 + Parquet/SQLite 存储层 + CacheResolver + 门面 API（K 线部分）+ 历史回填任务
- **第二期**：财务/元数据/标的池缓存 + 复权计算完善 + 数据校验 + 日终维护任务
- **第三期（暂缓）**：WS 实时采集进程 + 盘中半可变层。**2026-08-30 用户决定：WebSocket 暂时不可用，实时行情整体暂缓，优先回测能力**。计划已写（`docs/superpowers/plans/2026-08-30-data-center-phase3.md`），需要时启用
