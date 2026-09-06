# 日内盯盘系统设计（第八期）

日期：2026-09-05 · 状态：已确认（方案 A + 三节设计均经用户确认）

## 1. 需求

日内盯盘：当因子/行情达到某个值时，向用户发出买入/卖出信号。

- 用户用**自然语言**向 AI 描述盯盘条件（如"帮我盯 600869，价格达到近 20 日低价位、价格分位数 20% 以下时提醒买入"），AI 生成 Python 脚本注册进系统。
- 系统**常驻不间断运行**，自动执行已注册脚本；支持任务注册、启动/停止；记录每次产出的信号。
- 脚本的 Python 代码**直接存在数据库里**（不落文件），页面上可看可编辑。
- 每个任务有**买入灯、卖出灯**两个状态：条件首次满足（False→True）发一次提醒并亮灯，之后页面持续亮灯；条件不再满足（True→False）发一次提醒并灭灯。**提醒只发生在灯的亮/灭边沿**。
- 通知渠道：**Bark（iOS 推送 App）写死在代码里**——单人系统，不做渠道表、不做可插拔抽象；device key 放配置文件 `data/monitor_config.json`（gitignore 内，不进代码库）。每个任务行上有一个 `notify` 开关决定要不要推送。
- 标的范围：**固定自选股池**（每个任务自带标的，手工/AI 注册，非全市场扫描）。

## 2. 关键约束（数据源）

- TickFlow 当前套餐**无 WebSocket 推送权限**（`NO_WS_PERMISSION`，见 sdk-notes.md §11），实时数据只能走 **REST 轮询当日分钟K**（`tf.klines.intraday` 有权限，sdk-notes §11 盘中 REST intraday ✅）。
- 用户确认信号时效：**1 分钟级轮询**（每标的每分钟 1 次请求，远低于限流：分钟按只 60 次/分、批量 30 次/分×100 标的）。
- 历史分钟K深度限最近一年——盯盘只用当日分钟 + 历史日线，不受限。
- 复用现有模块：`DataCenter`（`get_klines` 当日段走 intraday 半可变层）、`FactorStore`（11 个内置因子，`import factors.factors` 显式注册）。

## 3. 架构（方案 A：独立守护进程 + SQLite 任务库 + webui 扩展）

```
┌─────────────────────────────────────────────────────┐
│ scripts/monitor_daemon.py（常驻守护进程，交易时段运行）        │
│  ├─ 调度器：每分钟一轮，按任务 interval_sec 到期的执行   │
│  ├─ 脚本运行时：exec 执行 tasks.script 的 check(ctx)   │
│  ├─ 边沿判定：DB 灯状态 vs 本次结果 → 买/卖 开/关      │
│  └─ 通知：边沿触发 → notify.send（Bark，key 读配置文件） │
└──────────────┬──────────────────────────────────────┘
               │ 读写
        data/monitor.db（SQLite, WAL）
               │ 读写
┌──────────────┴──────────────────────────────────────┐
│ webui（8666，现有进程）新增「盯盘」tab                  │
│  任务列表（买灯/卖灯）· 启停开关 · 信号历史 · 注册/编辑   │
└─────────────────────────────────────────────────────┘

数据源：守护进程 → DataCenter（当日 1m intraday + 历史日线）→ FactorStore
```

**核心边界**：守护进程不依赖 webui，webui 不依赖守护进程，**DB 是唯一接口**——启停、注册、改参数都是 webui 写表，守护进程每轮调度前重读表，天然即时生效。脚本只接触 `MonitorContext`，不直接碰 DataCenter（便于 mock 测试）。

### 否决的方案

- **B：盯盘循环塞进 FastAPI 后台线程**——webui 重启盯盘即断，耦合太紧。
- **C：系统 cron 调度**——无常驻状态、错误隔离差、启停要改 crontab。

## 4. 模块划分（新增 `src/monitor/`）

| 模块 | 职责 | 依赖 |
|---|---|---|
| `store.py` | monitor.db 全部读写：tasks/signals/channels 三表 CRUD，灯状态原子更新 | sqlite3（WAL） |
| `runtime.py` | 脚本契约：`MonitorContext` 数据接口 + 代码字符串 exec 加载 + 执行 `check(ctx)` + 异常捕获 | DataCenter、FactorStore |
| `notify.py` | Bark 推送 `send(text)`：读 `data/monitor_config.json` 拿 key，POST `api.day.app/push` | urllib（不加新依赖） |
| `daemon.py` | 主循环：交易时段判断、任务调度、边沿判定、写信号、错误计数 | 以上三者 |

入口脚本：`scripts/monitor_daemon.py`（启动守护进程）+ `scripts/monitor_cli.py`（register/list/show/toggle/delete 任务管理 CLI，盯盘专家 skill 的程序化入口，人也能用）。

## 5. DB 表结构（`data/monitor.db`，WAL 模式）

```sql
-- 盯盘任务（灯状态随任务一行）
tasks(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,          -- "600869 20日低位区"
  symbol TEXT NOT NULL,        -- 盯盘标的，如 "600869.SH"；一个任务一个标的，daemon 构造 ctx 时注入
  script TEXT NOT NULL,        -- Python 代码全文，必须定义 check(ctx)
  interval_sec INTEGER NOT NULL DEFAULT 60,
  enabled INTEGER NOT NULL DEFAULT 1,        -- 页面启停开关
  notify INTEGER NOT NULL DEFAULT 1,         -- 灯边沿时是否推送 Bark（0=只亮灯）
  buy_on INTEGER NOT NULL DEFAULT 0,         -- 买入灯
  sell_on INTEGER NOT NULL DEFAULT 0,        -- 卖出灯
  poll_count INTEGER NOT NULL DEFAULT 0,     -- 累计执行次数
  signal_count INTEGER NOT NULL DEFAULT 0,   -- 累计信号数（边沿数）
  last_run_at INTEGER,                       -- 上次执行 ms
  error_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,                           -- 最近一次报错（页面可见）
  created_at INTEGER NOT NULL
);

-- 信号历史（只记边沿，不记每次轮询）
signals(
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,         -- ms
  kind TEXT NOT NULL,          -- buy_on / buy_off / sell_on / sell_off
  price REAL,                  -- 触发时最新价
  message TEXT                 -- 脚本返回的 msg
);
```

## 5.1 配置文件（`data/monitor_config.json`，gitignore 内）

```json
{"bark_key": "<device_key>", "bark_server": "https://api.day.app"}
```

`bark_server` 可省略（默认官方 `https://api.day.app`）。守护进程启动时读一次；文件不存在或缺 `bark_key` = 推送功能关闭（只亮灯），并在启动日志里说明。

## 6. 脚本契约（MonitorContext）

AI 生成的脚本只定义一个 `check(ctx)` 函数（需要 import 时允许在 script 顶部自行 import，如 numpy/pandas），返回 dict：

```python
# 示例：用户说"帮我盯600869 价格达到近20日低价位（价格分位数20%以下时），提醒我买入"
def check(ctx):
    px = ctx.price()                     # 最新价（当日最后 1m bar 收盘）
    hist = ctx.daily(60)                 # 近 60 根日线 DataFrame（含今日实时合成日K）
    low20 = hist["low"].tail(20).min()
    in_zone = px <= low20 * 1.02         # 近20日最低价上方 2% 以内
    return {"buy": in_zone, "sell": None, "msg": f"现价{px} 20日低点{low20}"}
```

**ctx 4 个方法**（覆盖日线因子 + 分钟行情；ctx 由 daemon 用任务行的 `symbol` 构造，方法均不带 symbol 参数）：

| 方法 | 返回 | 实现 |
|---|---|---|
| `ctx.price()` | float 最新价 | 当日 1m 最后一根 close |
| `ctx.minute_bars()` | 当日 1m DataFrame | `dc.get_klines(symbol, "1m", today, now)`（intraday 半可变层，TTL 缓存） |
| `ctx.daily(n)` | 近 n 根日线 DataFrame | 历史日线 + 今日未完成日K（1m 聚合，复用现有 intraday 合成逻辑） |
| `ctx.factor(name, params, n)` | 因子 Series（按 timestamp 索引，n=取数窗口根数，须带够 lookback） | FactorStore（`import factors.factors` 由 runtime 统一做） |

**返回值约定**：`buy`/`sell` 为 `True/False/None`——`None` 表示该任务不管这盏灯（灯状态不变、永不通知）；`msg` 字符串随信号入库。脚本必须**无副作用、无状态**（每次轮询独立调用；需要跨轮状态的任务不支持，YAGNI）。

**执行方式**：`exec(script, namespace)` 取 `namespace["check"]`；加载失败（语法错/无 check）记 `last_error`，任务不执行。**本地纯自用，不做沙箱**（用户自己的代码，同现有策略脚本信任级别）。

## 7. 调度与边沿判定

- 主循环每分钟一轮（**最小调度粒度 60s**，`interval_sec` 小于 60 按 60 处理，前端输入框提示下限）；**交易时段**（9:25~11:30、13:00~15:00，含集合竞价尾声）才执行任务，非交易时段 sleep。交易日判断：当日 intraday 返回非空即在市（周末/节假日自然无数据、任务空转不报错——沿用半可变层"休市返回 0 行"语义，见 sdk-notes §11.5）。不维护交易日历表（YAGNI）。
- 每轮重读 `tasks` 表（启停/新注册/编辑即时生效）；任务到期（`now - last_run_at >= interval_sec`）才执行；同一轮内多任务**串行**执行（自选股池规模下足够，且天然控制请求速率）。
- 单任务执行流程：
  1. 构造 ctx（取数失败 → 记错误，跳过本轮）
  2. 跑 `check(ctx)`，异常 → `error_count+1`、`last_error` 记录，**不影响其他任务**；连续报错不自动停用（页面可见，用户决定）。超时不硬杀（同进程 exec 无法安全中断），只做**软超时**：耗时 > 30s 记 `last_error="slow check"` 提示
  3. `poll_count+1`、`last_run_at` 更新
  4. 边沿判定（对 buy、sell 各做一次）：
     - 结果 `True` 且灯=0 → 置 1，写 `signals(kind=*_on)`，`signal_count+1`，发通知
     - 结果 `False` 且灯=1 → 置 0，写 `signals(kind=*_off)`，`signal_count+1`，发通知
     - 结果与灯一致 → 什么都不做
     - 结果 `None` → 灯不动

## 8. 通知（Bark 写死，配置文件给 key）

单人系统，不做渠道抽象。**`notify.py` 就一个 `send(text)` 函数**：读 `data/monitor_config.json` 拿 key，POST Bark。

```python
# data/monitor_config.json: {"bark_key": "...", "bark_server": "https://api.day.app"(可省)}
def send(text: str) -> None:
    # POST {server}/push  JSON: {"device_key": key, "title": "盯盘信号", "body": text,
    #   "group": "盯盘", "sound": "bell", "level": "timeSensitive"}
    # 教程（docs/bark/使用教程.html）预留参数：level=critical 静音也响铃、
    # id 相同可更新同一条通知、markdown 排版 —— 首发只用 title/body/group/sound
```

- 通知文案：`【盯盘】600869 20日低位区 买入灯亮：现价12.34 进入20日低位区（2026-09-05 14:32）`；灭灯同理（`买入灯灭`）。
- **发送失败不抛异常**：记任务 `last_error`，信号照常入库（信号不丢，只是没推出去）。
- 任务 `notify=0`、或配置文件缺失/无 key：正常亮灯、写信号，不推送。
- Bark 推送已实测通过（2026-09-05，`scripts/test_bark.py`，官方服务器返回 code 200）。

## 9. webui「盯盘」tab（第三个 tab）

布局：

```
┌ 盯盘任务 ─────────────────────────────────────────────┐
│ ●买 ○卖  600869 20日低位区   60s  ✓运行中  [停用][详情]  │
│ ○买 ○卖  通鼎互联 金叉       60s  ⏸已停用  [启用][详情]  │
├ 信号历史（可按任务筛选）────────────────────────────────┤
│ 09-05 14:32  600869低位区  买入灯亮  12.34              │
└───────────────────────────────────────────────────────┘
详情抽屉：script 代码（可看可编辑，保存即生效）/ 名称 /
  interval_sec / notify 推送开关 / 启停 /
  poll_count / signal_count / error_count / last_error
[+ 新建任务]：名称 + 标的 symbol + 粘贴代码 + interval + notify 开关
```

后端 `webui/api.py` 新增 `/api/monitor/*`（全部只操作 monitor.db，与行情数据解耦）：

| 端点 | 说明 |
|---|---|
| `GET /api/monitor/tasks` | 任务列表（含灯状态/计数/last_error） |
| `POST /api/monitor/tasks` | 新建任务（name/symbol/script/interval_sec/notify） |
| `PUT /api/monitor/tasks/{id}` | 编辑（含 script 代码） |
| `POST /api/monitor/tasks/{id}/toggle` | 启停翻转 |
| `DELETE /api/monitor/tasks/{id}` | 删除任务 |
| `GET /api/monitor/signals?task_id=&limit=` | 信号历史 |

前端沿用第六期技术栈（React + antd），灯用 Badge/Tag 红绿点；**红=买入灯亮、绿=卖出灯亮**？——不，遵循前端既定「红涨绿跌」语义易混淆，灯用 **亮黄/灰灭** 区分状态，买卖用文字标签区分。

## 10. 错误处理汇总

| 场景 | 行为 |
|---|---|
| 脚本语法错/无 check | 记 `last_error`，任务跳过（不执行） |
| check 运行抛异常 | `error_count+1`、`last_error`，其他任务不受影响 |
| 取数失败（限流/网络/休市空数据） | 记错误跳过本轮；休市空数据不记错误（静默跳过） |
| 通知发送失败 | 记 `last_error`，信号已入库不丢 |
| 守护进程崩溃 | 人工重启（`scripts/monitor_daemon.py`）；灯状态在 DB，重启不丢状态 |
| 停牌（当日无 bar） | ctx 取数为空 → 跳过本轮，不报错 |

## 11. 测试方案

| 层 | 内容 |
|---|---|
| store | 三表 CRUD、灯状态原子翻转、信号写入（内存 SQLite `:memory:`） |
| runtime | exec 加载代码字符串、缺 check 报错、脚本异常被捕获隔离、ctx 四方法用 fake DataCenter 验证 |
| 边沿判定 | 纯函数覆盖全部迁移：亮/灭/保持/None 不动灯/灯初态 |
| daemon | fake ctx + 内存 DB 跑一轮调度：enabled=0 跳过、interval 未到跳过、错误计数、信号写入 |
| notify | send() mock HTTP 验证 URL 拼接与 JSON payload；发送失败不抛；配置文件缺失时静默跳过 |
| webui | FastAPI TestClient 走一遍 6 个端点 CRUD |
| 数据侧 | 全部用 fake/缓存数据，**不打真实接口**；真实盘中冒烟（注册一个简单任务跑 10 分钟看灯和通知）作为人工验收 |
| skill | monitor-expert 的验证管线：语法检查/干跑/历史回放各一例；CLI 增删改查走一遍 |

## 12. 边界（明确不做）

- 不做全市场扫描（限流不允许，且需求是固定自选股）
- 不做沙箱/权限隔离（本地自用，脚本信任级别同策略脚本）
- 不做跨轮状态的脚本（每次轮询独立调用）
- 不做自动下单/接实盘（纯信号提醒，用户手动操作）
- 不做交易日历表（用"当日 intraday 是否非空"判断在市）
- 不做多渠道/渠道表（Bark 写死；将来真要加微信/钉钉，再改造 notify.py 不迟）

## 13. 盯盘专家 skill（`.claude/skills/monitor-expert/`）

配套交付一个项目级 skill（同 `backtest-expert` 的玩法）：用户用自然语言说盯盘方案，skill 负责生成脚本、验证、注册、管理、诊断。定位 = **技术专家 + 金融专家**：合理运用数据模块 + 因子模块组合出正确的 `check(ctx)`，并把金融话术翻成严谨的条件定义。

**职责（四件事）**：

1. **生成**：自然语言 → `check(ctx)` 脚本。澄清条件里的话术（"低位区"= 近 20 日最低价上方 2%？还是 60 日价格分位数 <20%？——给出默认并在注册时写明口径）；优先用因子库（`ctx.factor`）而非手搓指标；脚本无副作用、无状态、每次轮询独立。
2. **验证（注册前必做）**：① `compile()` 语法检查；② 用真实 DataCenter 构造 ctx **干跑一次**确认不抛异常、返回结构合法（buy/sell 为 bool/None）；③ **历史触发回放**：用近 N 天日线把同一条件逐日评估，报告"过去 3 年会触发约 X 次、最近三次触发日期"——让用户判断条件太松还是太严（这是金融专家的核心价值，防止注册一个每分钟都亮灯或永远不响的废条件）。
3. **注册/管理**：通过 `scripts/monitor_cli.py` 注册任务（写入 monitor.db）、启停、查看任务列表与灯状态。
4. **诊断**：用户问"为什么没提醒"时，查任务的 `last_error`/`error_count`/`poll_count`、信号历史，结合脚本逻辑给出解释（条件没满足 / 脚本报错 / 停牌无数据 / 非交易时段 / notify 关了 / 推送失败）。

**skill 内置知识**（写进 SKILL.md，防止 AI 自由发挥出错）：

- `MonitorContext` 四方法契约与返回结构约定（本 spec §6）
- 数据约束：WS 无权限（轮询 1m）、分钟K深度 1 年、限流阈值、停牌日无 bar、休市 intraday 返回空
- 因子库用法：必须 `import factors.factors`；11 个内置因子及参数；日线因子用于"今日"时含未完成日K 的口径
- 边沿提醒语义：脚本只需返回条件当前是否成立，亮灭灯/去重由 daemon 负责——**脚本里不要自己写"只提醒一次"逻辑**
- 金融话术 → 条件速查表（低位区分位数、放量/量比、金叉死叉、多头排列、尾盘时段判断用 `ctx.minute_bars()` 的最后一根时间戳等）

### 13.1 数据/因子模块调用速查（SKILL.md 正文内容）

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

### 13.2 示例脚本库（SKILL.md 正文内容，AI 生成时参照改写）

**例 1 · 20 日低位区（震荡市低吸，用户原话场景）**

```python
def check(ctx):
    px = ctx.price()
    hist = ctx.daily(60)
    low20 = hist["low"].tail(20).min()
    in_zone = px <= low20 * 1.02          # 近20日最低价上方 2% 以内
    return {"buy": in_zone, "sell": None,
            "msg": f"现价{px:.2f} 20日低点{low20:.2f}"}
```

**例 2 · 回踩 MA20 不破（趋势票持股线，对应周五研究结论"线上持股线下不碰"）**

```python
def check(ctx):
    px = ctx.price()
    ma20 = ctx.factor("ma", {"n": 20}, 60).iloc[-1]
    near = abs(px - ma20) / ma20 <= 0.01   # 距 MA20 1% 以内
    above = px >= ma20                      # 且没跌破
    return {"buy": near and above, "sell": (px < ma20 * 0.98),
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
    return {"buy": breakout, "sell": None,
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
    return {"buy": bool(cross), "sell": None,
            "msg": f"MA5={ma5.iloc[-1]:.2f} MA20={ma20.iloc[-1]:.2f}"}
```

**例 5 · 尾盘跳水避险灯（14:30 后当日跌幅超 1% 亮卖出灯，周五研究的应用）**

```python
def check(ctx):
    bars = ctx.minute_bars()
    if bars.empty:
        return {"buy": None, "sell": None, "msg": "无当日数据"}
    last_ts = bars["timestamp"].iloc[-1]
    hhmm = (last_ts // 1000 % 86400 + 8 * 3600) // 60  # 北京时间分钟数
    if hhmm < 14 * 60 + 30:
        return {"buy": None, "sell": False, "msg": "未到尾盘"}
    d = ctx.daily(2)
    prev_close = d["close"].iloc[-2]         # 昨收（倒数第二根=昨天）
    drop = ctx.price() / prev_close - 1
    return {"buy": None, "sell": drop <= -0.01,
            "msg": f"尾盘当日跌幅{drop:+.2%}"}
```

**例 6 · 成本止损灯（用户报成本价，AI 写死进脚本——脚本无状态，成本由用户提供）**

```python
COST = 12.30   # 用户持仓成本，注册时由用户告知

def check(ctx):
    px = ctx.price()
    atr = ctx.factor("atr", {"n": 14}, 30).iloc[-1]
    stop = COST - 2 * atr
    return {"buy": None, "sell": px < stop,
            "msg": f"现价{px:.2f} 止损线{stop:.2f}(成本{COST}-2ATR)"}
```

**边界**：skill 只生成和注册脚本，不改盯盘系统本身；脚本涉及下单/交易动作的一律拒绝（纯提醒系统）。
