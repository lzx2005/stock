# HELP.md — AI 入口总目录（每个 AI 进仓库先读这一份）

> 给 **AI 读**的入口文档。README.md 是给人读的。本文件让新 AI 一份读完就进入状态：
> 项目是什么、需求、5 期迭代、当前进度、待办、代码结构、文档结构、工作规则。
> 读完本文件还不足以动手时，再按「文档结构」一节按需深读。

---

## 1. 一句话

**A 股量化投研工具**：本地数据中心（TickFlow 付费 API 回源缓存）→ 回测引擎（验证哪些条件有利于收益）→ 因子库（因子定义+算好的值，回测直接复用）→ 策略库（策略列表+版本，对比每次优化有没有进步）。

本地优先应用。源码已发布 GitHub（2026-09-05 起）；**数据、密钥、`.claude/` 本地状态永不入库**（.gitignore 已配，见 §8）。他人从零跑起来的准备见 README「环境准备」。

## 2. 核心需求（用户原话提炼）

- **AI 不碰数据与结果（2026-09-06 用户立规）**：AI 会幻觉，所有数据和结果（选股、行情、回测、因子、盯盘）必须由程序和算法计算得到；AI 只负责与人交互、理解需求；盯盘/回测等流程必须由 Python 脚本严格验证（详见 CLAUDE.md 同名强制规则）。
- **不做选股系统**。用户原话："根据条件选股这种事情，我们不做了……我们主要进行回测模拟验证想法。"
- 产品形态：回测算出来**哪些条件有利于收益** → 你给出选股策略（每因子转成**同花顺一句话条件**，如 `量比>1.5`、`5日涨幅>10%`）→ 用户去同花顺手动选股买入。
- 回测**金标准测试用例**："5日均线上穿20日均线买入，5日均线下穿20日均线卖出"（MaCross，已作为 golden 测试固化）。

## 3. 技术栈 / 运行环境

| 项 | 值 |
|---|---|
| Python | ≥3.11，venv：`.venv/bin/python` |
| 依赖 | `tickflow[all]>=0.1.17`（数据源）、`duckdb`、`pandas`、`pyarrow`、`fastapi>=0.110`、`uvicorn>=0.29`（webui 后端） |
| 前端 | **方案未定**（用户 2026-09-06 明确）。仓库内有 `frontend-gpt/` 实验实现（React+Vite，5178，proxy→8666），另有外部独立工程方案；采用哪个待用户决定 |
| API Key | `TICKFLOW_API_KEY` 在 `~/.zshrc`；**非交互 shell 不加载 `.zshrc`，跑真实数据前先 `source ~/.zshrc`** |
| 测试 | `.venv/bin/python -m pytest tests/`（`--timeout=60`），当前 **232 全绿** |
| 数据 | `data/`（已 gitignore，勿提交）：`klines/`（parquet 分区）、`meta.db`、`factors/`、`strategies/`（策略库 JSON）。**周期目录名须走 `period_dir_token()`**：大小写不敏感文件系统上 `period=1m`/`period=1M` 会撞目录，月线落盘为 `period=1Mo`（2026-09-06 修复，详见 README 数据存储一节） |
| 权限实测 | 分钟 K **已可用**（深度限最近一年）；WS 实时推送**无权限**（代码已实现，待开通） |
| 前端规格 | **页面/按钮/交互逻辑 + 接口规格见 `docs/FRONTEND.md`（功能文档，改前端必读、改完必同步）**；任何前端方案都以此为准 |

## 4. 迭代历史（8 期已实现；第六期待浏览器冒烟、第八期待交易日盘中冒烟；232 测试全绿）

| 期 | 计划 | 内容 | 说明 |
|---|---|---|---|
| 一期 | data-center-phase1 | K线缓存 + 历史回填 | 本地优先、缺失回源、查到即存；全市场回填 |
| 二期 | data-center-phase2 | 复权 + 财务/元数据 + 校验 + 日终维护 | 前复权计算、财务/标的池缓存、quality 校验 |
| 三期 | data-center-phase3 | WS 实时采集 + 盘中半可变层 | **实现+测试通过，但盘中真实验证被 NO_WS_PERMISSION 阻塞（未勾，见 §7 待办）** |
| 四期 | backtest-phase4 | 回测引擎 + 真实回填验证 | indicators/broker/strategy/engine/performance + 示例 + 日线全市场/分钟抽样真实回填 |
| 五期 | factors-phase5 | 因子库 | 定义注册表 + 计算 + parquet 存储复用；双均线改造走因子库 golden 对拍 |
| 六期 | webui-phase6 | Web 查询界面 | **实现完成**：后端（数据层 4 只读方法 + FastAPI 7 端点）+ 前端（Vite+React+antd+ECharts 两 tab）生产构建通过；167 测试全绿；待浏览器人工确认 |
| 七期 | strategy-phase7 | 策略模块 | 策略列表+版本：`create`/`record`（自动对比 v1+上一版，进步/退步/部分改善）/`compare`/`rename`/`delete`；build_report 出"七、版本对比"章节；backtest_meta.json 边车；33 新测试，全量 200 |
| 八期 | monitor-phase8 | 日内盯盘系统 | **实现完成**（spec `2026-09-05-intraday-monitor-design.md`）：`src/monitor/`（store/runtime/notify/daemon）+ monitor.db（tasks/signals，脚本代码存库内）+ 边沿亮灭信号灯 + Bark 推送（key 在 `data/monitor_config.json`，已实测）+ `scripts/monitor_daemon.py` 守护进程 + `monitor_cli.py` + webui「盯盘」tab（6 端点）+ 盯盘专家 skill（`.claude/skills/monitor-expert/`，含 validate_watch 三段验证）；+27 测试；**任务 description 字段**（原理/实现/回放结果：store `_migrate` 自动补列 + CLI `--description` + webui 列表悬停全文 + 抽屉可编辑；+1 测试）；**待交易日盘中冒烟**（见 §7 待办）；2026-09-06 双灯(buy/sell)→单信号灯(lamp_on，kind on/off)，DB 自动迁移，+1 迁移测试 |

各期 Checkbox 状态：实施步骤已勾；历史计划中的 Commit 步保持未勾（彼时纯本地不用 git；2026-09-05 起项目已发布 GitHub，后续改动正常提交）。

## 5. 代码结构

```
src/
├── datacenter/          # 数据中心（数据层）
│   ├── api.py            # DataCenter 门面（get_klines 等统一入口）
│   ├── client/tickflow_client.py  # TickFlow SDK 封装（限流 ratelimit.py）
│   ├── store/            # klines.py(K线 parquet 缓存，duckdb 只读走 _duck.py 独立连接，线程安全) financials.py meta.py realtime.py
│   ├── adjust.py         # 前复权计算
│   ├── intraday.py       # 盘中半可变层（当日未完成 K）
│   ├── resolver.py       # CacheResolver（区间切分/合并/逐段取数）
│   ├── quality.py        # 数据质量校验
│   └── jobs/             # backfill.py(可断点续传) daily_maintenance.py ws_collector.py
├── backtest/             # 回测引擎（策略层）
│   ├── indicators.py     # 纯 pandas 指标：ma/ema/rsi/macd/kdj/atr/boll
│   ├── broker.py         # Order/Position + 撮合(次bar开盘) + 佣金/印花税/滑点 + 涨跌停/T+1/一手取整
│   ├── strategy.py       # Strategy 基类 + Context(buy/sell/close/positions/cash/history)
│   ├── engine.py         # BacktestEngine：事件驱动循环 + 多标的时间对齐 + 绩效
│   └── performance.py    # 总收益/年化/回撤/夏普/胜率/交易明细
└── factors/              # 因子库（策略层）
    ├── registry.py       # FactorDefinition(frozen dataclass) + register_factor/get_factor/list_factors + 指纹
    ├── compute.py        # apply_factor（校验输入列 → defn.fn）
    ├── factors.py        # 11 个内置因子（ma/ema/rsi/atr/macd_hist/kdj_j/boll_up/boll_low/vol_ratio/mom/bias），每个 doc 带同花顺条件句
    └── store.py          # FactorStore：parquet 分区 + 惰性取数 + 缺口补算(lookback) + 原子写 + warm/drop/refresh + list_stored/load_stored
├── strategy/             # 策略库（第七期）：策略列表 + 版本管理（纯文件系统，无 DataCenter 依赖）
│   ├── errors.py         # StrategyError / StrategyNotFoundError / VersionNotFoundError
│   ├── store.py          # StrategyStore：目录式 JSON（data/strategies/<id>/versions/<N>/）+ 原子写 + import_version 登记 + 自动对比 v1+上一版
│   └── compare.py        # 纯函数：comparable / metric_delta / excess_return / judge_verdict / build_comparison
└── webui/                # Web 查询界面（第六期）
    ├── app.py            # create_app(data_dir) 工厂：三只读存储 + MonitorStore；若 frontend/dist 存在则挂载（兼容旧布局，现已无内置前端）
    ├── api.py            # /api 端点：periods/coverage/klines/factors/factor-dirs/factor-values（scripts/serve.py 启动 8666）；klines 默认只读缓存，?refresh=1 懒构造 DataCenter 回源补最新（含当日盘中 bar，失败退回缓存）
    └── monitor_api.py    # /api/monitor 六端点（第八期）：tasks CRUD/toggle + signals
├── monitor/              # 日内盯盘（第八期）
│   ├── store.py          # MonitorStore：data/monitor.db（tasks/signals 两表，WAL），灯状态/计数/信号/任务 description（_migrate 自动补列）
│   ├── runtime.py        # MonitorContext（price/minute_bars/daily/factor + asof_ms 回放模式）+ load_check/run_check + DataError
│   ├── notify.py         # Bark 推送 send()（key 读 data/monitor_config.json，缺失/失败不抛）
│   └── daemon.py         # MonitorDaemon：每分钟 tick，交易时段调度、边沿判定（edge_transition）、错误隔离
```
（原前端已迁出；本仓库新增 `frontend-gpt/` 独立设计版本，三页 React 实现已完成并通过联调。外部独立工程实现三 tab——行情/因子/盯盘 MonitorBoard，经 dev proxy 对接 8666；规格见 docs/FRONTEND.md）
Skill 体系（用户与本项目的主要交互方式，均随仓库入库）：`stock-start-up`（新用户初始化引导：环境/key/回填/冒烟）、`backtest-expert`（回测+PDF 报告）、`monitor-expert`（盯盘脚本+注册）、`trade-review`（交割单复盘）；均在 `.claude/skills/`。
盯盘脚本契约（spec §6，2026-09-06 改为单灯）：AI 生成的脚本只需定义 `check(ctx)` 返回 `{"on": bool|None, "msg": str}`——一个任务一盏信号灯，条件成立=灯亮（买卖含义由任务名称/说明表达，系统不预设方向），None=本轮不判断；灯亮灭去重由 daemon 边沿判定负责（信号 kind 为 on/off），脚本不写"只提醒一次"逻辑。管理入口：`scripts/monitor_daemon.py`（守护进程）、`scripts/monitor_cli.py`（register/list/show/toggle/delete）、盯盘专家 skill `.claude/skills/monitor-expert/`（自然语言→脚本→三段验证 validate_watch.py→注册/诊断）。
策略库**版本对比语义**（spec §5）：record 新版本时自动同时对比 **v1（原版）** 与 **上一版**；判定用主指标 4 项（total_return/超额收益/max_drawdown/sharpe）——无一项变差且（≥2 项变好 或 总收益变好）= 进步；总收益变差 或 变差项 ≥2 = 退步；否则部分改善。**可比性纪律**：symbols/period/复权口径/区间/初始资金/成本模型(6字段) 全等才可比；策略 params 差异不阻断（那是被测对象）。改标的/区间/成本模型建议另建策略。

**因子库关键语义**（spec §6.2）：
- 指纹 `sha1(name|params_json|version|adjust)[:16]` → 参数/版本/复权变更自动换目录，旧缓存不误删。
- 因子必须因果（rolling/ewm/shift/pct_change），支持整窗预取 + 按时间点索引，无前视。
- 缺口补算带 `lookback` seed（滚动因子缺口起始即满窗）；**等价性边界**：平移不变滚动因子（ma/boll/vol_ratio/mom/bias）逐根精确；递推平滑因子（rsi/kdj_j/atr）是收敛近似，要精确用 `refresh()`。
- **显式注册**：`factors/__init__.py` 不自动注册，消费方必须 `import factors.factors`，否则 `FactorUnknownError`。

## 6. 文档结构

```
README.md                    # 给人读：功能/上手/技术架构（顶部含系统架构图）
HELP.md                      # 给 AI 读：本文件（入口总目录）
CLAUDE.md                    # 工作规则（每个 AI 先读的强制性规则，含"先读 HELP.md"）
images/
└── architecture.png         # 系统架构图（README 顶部引用；由 docs/architecture-diagram.md 文字描述生成）
animation-plans/             # 旧前端的动画审计计划存档（improve-animations 产出，001~006 全部 DONE；前端已迁出，仅作历史记录）
docs/
├── architecture-diagram.md  # 架构图文字描述（分层/组件/四条数据流/约束，供画图 AI 生成架构图）
├── FRONTEND.md              # 前端功能文档：页面/按钮/交互逻辑 + §5 全量 API 参考（§5.0 跨工程接入代理说明；请求参数/返回字段/错误码 + §7 变更记录；只管功能，视觉由设计 AI 自定；改前端必同步）
├── sdk-notes.md             # TickFlow SDK 实测：限流/异常/字段/权限（含 NO_WS_PERMISSION 记录）
├── openapi.json             # SDK 接口原始快照
└── superpowers/
    ├── specs/               # 设计文档（权威）：data-center-design、factor-library-design、strategy-design、intraday-monitor-design（八期盯盘）
    └── plans/               # 实施计划（checkbox 版，进度索引）：phase1~phase8
```

- **spec = 设计权威**；plan = spec 的论据 + 实施步骤（checkbox 进度）。
- 四期回测引擎**无独立 spec**，设计决策在 `2026-08-30-backtest-phase4.md` 计划内（架构/撮合时序/成本模型）。
- 恢复工作流程（省 token）：读 `docs/superpowers/plans/` → 找第一个未勾 Step → 从那里继续，无需重读全部代码。

## 7. 当前进度与待办

**frontend-gpt（2026-09-06，已完成）**：独立 React 前端，行情/因子/盯盘三页；对齐单信号灯 `lamp_on` / `on` 契约、标的归组与详情周期切换。含日期与服务端明细分页、完整区间 ECharts、回源错误缓存提示、盯盘 CRUD、状态保持、GSAP 导览及手机适配。**5 单元测试 + 8 浏览器场景通过，生产构建通过**；真实 API 只读冒烟读到 5,558 个标的、726 根指数 K 线、11 因子与现有任务，零浏览器运行错误。计划见 `docs/superpowers/plans/2026-09-06-frontend-gpt.md`；源码分 `src/pages/`、`src/components/`、`api.ts`、`domain.ts`、`types.ts`，验证脚本在 `tests/`，启动说明在 `frontend-gpt/README.md`。启动：`cd frontend-gpt && npm ci && npm run dev`，访问 `http://127.0.0.1:5178`；`npm run build && npm run preview` 在 4178 预览。后端仍单独运行 8666。

**已完成**：5 期全部实现；第六期 Web 查询界面实现完成（后端 4 只读方法 + FastAPI 7 端点 + 前端 Vite/React/antd/ECharts 两 tab：行情页左右分栏+红涨绿跌 K 线+报价头，生产构建通过、真实数据冒烟）；**第七期策略模块实现完成**（策略列表+版本：`create`/`list`/`record`/`compare`/`rename`/`delete`，record 自动对比 v1+上一版并判定进步/退步/部分改善，build_report 在版本目录出含"七、版本对比"章节的 PDF，backtest_meta.json 边车补全决定参数；33 新测试，全量 200 全绿）；MaCross golden 证明因子库路径与现算逐笔一致。

**待办 / 未决**：

**A. 等用户 / 等外部依赖**
1. **第八期盘中真实冒烟**：交易日交易时段跑 `source ~/.zshrc && .venv/bin/python scripts/monitor_daemon.py` 10 分钟，注册一个必亮灯任务确认 灯亮→Bark 推送→页面可见→信号入库（计划 Task 9 Step 4）。
2. **第六期人工冒烟确认**：浏览器开 `localhost:8666` 验证两 tab（点行下钻、K 线图渲染、搜索/分页）——自动化已全绿，只剩肉眼确认；确认后 phase6 正式完成（Commit 步除外）。
3. **WS 盘中真实验证**（phase3 唯一未勾实施步）：spike 需交易时段跑 5 分钟验证落盘+行数增长，被 `NO_WS_PERMISSION` 阻塞；开通权限后做（见 sdk-notes.md §11）。
4. **交易复盘 skill 迭代**（独立工作线，任务 #31）：摊平加仓归因缺口，等用户 viewer 反馈（此前在 localhost:3117）；其 workspace 位置需确认。
5. **回测专家 skill 迭代**（独立工作线）：`backtest-expert` 已建（`.claude/skills/backtest-expert/`，依赖 reportlab+matplotlib），3 例评估 with-skill 与无 skill 均 27/27（9 条程序化断言区分度为零——基线靠仓库示例也能全做，价值在定性：统一 schema/六章 PDF/同花顺一句话/免手写 PDF 管线）。已完成 ATR 止损对拍：skill 版 eval-2 原报 -9.39% 系 `_avg_cost` 清仓残值未归零 bug（成本虚高→过早止损），修复后 -42.39% 与基线 -42.72% 收敛；SKILL.md 已加"成本/止损线实现的坑 + 1 笔人工对拍"防坑指引；评估面板已关闭，等用户反馈后迭代。

**B. 候选扩展（无排期）**
6. **因子库扩展**：更多因子、全市场 warm、接入日终维护自动更新。

**C. 主线诉求**
7. **策略研究**：用回测验证"哪些条件有利于收益"，产出可翻译成同花顺一句话条件的策略。
8. **策略持续优化闭环**（第七期已建基础，已投入使用；标的与收益数字已脱敏）：策略 #1「双均线金叉·缠绕过滤」（低波银行股）已迭代 v1~v3——v2 加**快线走强过滤**（金叉时 MA5 现值 > 8 日前 MA5 才买，滤均线缠绕期假突破），vs v1 判定**进步**（收益/回撤/夏普全面改善）；v3 加**量比过滤**（金叉当日量比>1.5 才买，滤无量上涨），vs v1/v2 判定**退步**——低波银行股金叉基本不放量，1.5 阈值过严致过度过滤；备选"开口过滤"（等乖离≥1.5%）追高反而恶化收益，已否决。结论：低波银行股双均线不宜加量比硬过滤（或需降阈值再验）。策略 #2「双均线金叉·高波动股池」（多标的共享资金池分槽）：v1 纯金叉基线最优；v2 量比>1.5 过滤 vs v1 判定**退步**——放量金叉常接近短期高潮点，反而买到贵价，量比>1.5 作为买入硬过滤已两度否决。回撤控制迭代：回撤主因是死叉出场太慢 + 下跌趋势逆势开仓的**区间性磨损**；v3 趋势过滤（收盘>MA60 才买）小压回撤但收益大降；v4 ATR 止损（已对拍验证正确）挡不住连续亏损区间、被甩下车后错过反弹；v5 双保险仍得不偿失。结论：高波动股双均线的回撤主要来自区间性磨损，技术过滤压回撤的代价是收益砍半，v1 纯金叉仍最优。继续迭代 → `record` 新版本看进度（可比性纪律：固定标的/区间/成本模型）。另：**周五尾盘跳水统计验证**（2026-09-04，报告在本地 `reports/friday-tail-risk/`，不入库）——上证近1年周五尾盘(14:30→收盘)下跌概率约 70%（其他日约 38%，统计显著），周五是唯一日均收益为负的交易日；"周五14:30清仓→周一开盘买回"规则指数口径年累计小幅正贡献（价值在躲大跌周末，非每周稳赚；条件版"上午弱才撤"无效，要撤就无条件撤）。成因检验：月末/季末周五反而跳得轻、跳水不放量 → 否掉"流动性紧张"，实为周末风险溢价的无量阴跌。反向低吸检验：指数层面跳水后周一无补偿反弹；个股层面"周五收跌+站上MA20"低吸不如"周五收涨+站上MA20"动量跟进——赚的是动量延续不是跳水反转，跌破均线的跳水股是接飞刀。参数检验：MA20 并不特殊，MA10~60 单线过滤效果等同，均线多头排列（站上5/10/20/60）过滤更强。

> 注：历史计划的 Commit 步保持未勾（彼时纯本地不用 git）；2026-09-05 起源码已发布 GitHub，新改动正常提交。数据/密钥/`.claude/` 本地状态永不入库（.gitignore 已配）。

## 8. 工作规则（CLAUDE.md 摘要，全规则见 CLAUDE.md）

- **每次改动后同步更新本文件**（强制，重要）：完成 Step、改代码结构/接口/命令、新增或解决待办、测试数变化……**同一次会话内**把本文件相应小节改到位。本文件必须永远反映仓库当前真实状态，绝不滞后。
- **git**：源码已发布 GitHub（2026-09-05 起），改动正常提交；**`data/`、`reports/`、密钥、`.claude/` 本地状态（workspace / evals / settings.local.json / data）永不入库**——.gitignore 已配好，勿绕过；历史计划的 Commit 步保持未勾（历史记录）。
- **计划 checkbox 维护**：每完成一个 Step 立即 `- [ ]`→`- [x]` 随代码入库；以 `>` 开头的行和举例中的 `- [ ]` 不是待办，别勾。
- **跑真实数据前** `source ~/.zshrc`（拿 TICKFLOW_API_KEY）。
- **跑测试**：`.venv/bin/python -m pytest tests/`。
- **`data/` 勿提交**。
- 用户关注**省 token**：多用计划 checkbox 恢复，别整仓库重读。
- 用户**频繁切换 AI**：换 AI 后先读本文件进入状态。

## 9. 常用命令速查

独立 React 前端：`cd frontend-gpt && npm ci && npm run dev`（5178）；同目录 `npm test`、`npm run test:e2e`（需启动 dev server、本机 Chrome）、`npm run build`。

```bash
source ~/.zshrc
.venv/bin/python -m pytest tests/                    # 全量测试（232）
.venv/bin/python -m pytest tests/test_factor_store.py -v   # 单文件
.venv/bin/python scripts/factor_warm.py --symbols 600000.SH --factors ma,rsi --period 1d --years 3   # 因子预热
.venv/bin/python -m examples.run_backtest           # 跑 MaCross 真实数据
.venv/bin/python scripts/validate.py                 # 数据抽样校验
.venv/bin/python scripts/serve.py                    # 启动 Web 查询后端（127.0.0.1:8666，默认只读；前端选中标的自动 refresh 回源补最新）

# 策略库（第七期）
.venv/bin/python scripts/strategy_cli.py create --name "双均线金叉+ATR止损" --desc "..."    # 新建策略 → 返回 id
.venv/bin/python scripts/strategy_cli.py list             # 列表（id/版本/总收益/夏普/进度判定）
.venv/bin/python scripts/strategy_cli.py show --id 1      # 策略详情
.venv/bin/python scripts/strategy_cli.py versions --id 1  # 版本列表
.venv/bin/python scripts/strategy_cli.py show-version --id 1 --version 2   # 某版本决定参数+结果摘要（省 token，不读交易明细）
.venv/bin/python scripts/strategy_cli.py record --id 1 --from reports/<scratch> --note "相对上一版的改动"   # 登记新版本（自动对比 v1+上一版）
.venv/bin/python scripts/strategy_cli.py compare --id 1 --version 2        # 重算对比（幂等）
.venv/bin/python scripts/strategy_cli.py rename --id 1 --name "新名"
.venv/bin/python scripts/strategy_cli.py delete --id 1 --yes
.venv/bin/python .claude/skills/backtest-expert/scripts/build_report.py data/strategies/1/versions/2/   # 版本目录出 PDF（v≥2 含"七、版本对比"）

# 盯盘（第八期）
bash scripts/start.sh                           # 一键启动盯盘守护进程+Web API（serve.py 纯 /api，无内置前端；后台，日志/pid 在 data/logs/）
bash scripts/stop.sh                            # 一键停止（只停 start.sh 启动的进程）
.venv/bin/python scripts/monitor_daemon.py      # 或前台单独启动盯盘守护进程（Ctrl+C 停）
.venv/bin/python scripts/monitor_cli.py list         # 任务列表（灯/启停/错误计数）
.venv/bin/python scripts/monitor_cli.py register --name "600869 低位区" --symbol 600869.SH --script-file /tmp/x.py [--description "原理/实现/回放"]
.venv/bin/python scripts/monitor_cli.py show 1 / toggle 1 / delete 1 --yes
.venv/bin/python scripts/validate_watch.py x.py 600869.SH --days 750   # 注册前三段验证：语法/干跑/历史回放
# 或直接对 AI 说"帮我盯 ……"——monitor-expert skill 自动接管生成+验证+注册
```
