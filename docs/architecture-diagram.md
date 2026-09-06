# Architecture Diagram — 本项目架构图的文字描述

> 给画图 AI 的输入文档：本文用文字完整描述系统架构的分层、组件与数据流向，请据此绘制架构图。
> 建议图风格：分层架构图（自上而下六层），组件用圆角矩形，外部系统用六边形或不同底色，数据流向用带箭头连线并标注内容；关键约束用虚线框或脚注标注。

## 系统定位

一个 **本地优先的 A 股量化投研工具箱**：所有数据缓存在本机，所有计算（回测/因子/盯盘/复盘）由本地 Python 程序完成；AI 只负责与人交互，不碰数据与结果。

## 分层与组件（自上而下）

### 第 0 层 · 用户与 AI 交互层

- **用户**：通过自然语言与 AI 对话（Claude Code）
- **AI + Skills**（四个 skill，AI 的唯一职责是理解需求并调用程序）：
  - `stock-start-up` 初始化引导（配 key、回填数据、冒烟验证）
  - `backtest-expert` 回测专家（自然语言 → 回测 → PDF 报告 → 同花顺条件句）
  - `monitor-expert` 盯盘专家（自然语言 → 盯盘脚本 → 三段验证 → 注册任务）
  - `trade-review` 复盘专家（交割单 → 时机评估/亏损归因 → 改进建议）

### 第 1 层 · 外部依赖（图最上方或最下方的外部实体）

- **TickFlow API**（付费数据源：K线/财务/元数据/标的池，REST + WS）
- **Bark**（iOS 推送服务，盯盘提醒的出口）
- **同花顺**（人手动执行选股/买卖的终端，不在系统内——用虚线表示）

### 第 2 层 · 采集与门面

- **DataCenter 门面**（唯一数据入口）：CacheResolver（缓存命中/缺口决策）
- **TickFlowClient**：SDK 薄封装（限速 + 重试 + 批量）
- **采集 Jobs**：backfill（全市场回填，断点续传）、daily_maintenance（日终固化）、ws_collector（盘中 WS 采集，当前无权限、代码就绪）

### 第 3 层 · 存储层（本地，`data/`）

- **KlineStore**：K 线 Parquet 分区（year/month）+ DuckDB 查询；只存原始价
- **IntradayCache**：盘中半可变层（当日数据，TTL 60s，不污染永久覆盖）
- **RealtimeStore**：WS 实时快照（按日分区）
- **MetaStore / FinancialStore**（meta.db，SQLite）：coverage 覆盖索引、标的元数据、财务、校验报告
- **FactorStore**：因子值 Parquet 分区（按指纹目录）
- **StrategyStore**：策略库 JSON（`strategies/<id>/versions/<N>/`）
- **MonitorStore**（monitor.db，SQLite）：盯盘任务（含脚本源码）+ 信号历史

### 第 4 层 · 计算引擎层

- **本地复权 adjust**（前/后复权计算，基于缓存的除权因子）
- **回测引擎 backtest**：indicators（指标库）→ strategy（策略基类）→ engine（事件驱动、无前视、次 bar 开盘成交、T+1/涨跌停/费用）→ performance（绩效/权益曲线）
- **因子库 factors**：registry（定义+指纹）→ compute（计算）→ store（落盘复用）
- **策略对比 compare**：新版本自动对比 v1 与上一版，判定进步/退步/部分改善
- **盯盘运行时 monitor**：runtime（脚本契约 check(ctx) + MonitorContext 取数）→ daemon（交易时段每分钟轮询、灯边沿判定）→ notify（Bark 推送）

### 第 5 层 · 服务与交付层

- **Web API**（FastAPI，127.0.0.1:8666）：`/api` 只读查询（行情/因子）+ `/api/monitor` 盯盘管理；默认离线只读，`refresh=1` 才回源
- **交付物**：回测 PDF 报告 + 同花顺条件句；盯盘 Bark 推送；复盘报告

## 关键数据流（建议画成四条带颜色的流）

1. **查询流**：用户/skill → DataCenter → 本地存储命中即返回；缺口 → TickFlowClient 回源 → 落库 → 返回
2. **回测流**：backtest-expert → 回测引擎 →（因子走 FactorStore 惰性取数）→ performance → 策略库版本对比 → PDF 报告
3. **盯盘流**：monitor-expert → validate_watch 三段验证 → 注册进 MonitorStore → daemon 交易时段轮询（ctx 从 DataCenter 取当日分钟/日线）→ 灯边沿 → signals 表 + Bark 推送
4. **复盘流**：trade-review → analyze_trades.py（脚本算客观指标）→ 对照 DataCenter 真实行情 → 复盘报告

## 必须体现的约束（用标注或图例表达）

- **AI 不碰数据**：AI/Skill 层与计算/存储层之间画一条"只传需求与程序输出"的边界——所有数值结论由程序产生
- **本地优先**：存储层是系统的中心，外部 API 只是缺口补给
- **密钥纪律**：TICKFLOW_API_KEY 在环境变量，Bark key 在 `data/monitor_config.json`，均不入库
- 当前限制：WS 无权限（ws_collector 待开通）；分钟数据深度限最近一年
