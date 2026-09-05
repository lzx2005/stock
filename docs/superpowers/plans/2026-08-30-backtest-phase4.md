# 第四期：回测引擎 + 真实回填验证

> 2026-08-30 启动。git 延续前几期约定：本期不接 git，所有 Commit 步骤保持未勾，用户说"提交"时统一处理。
> 回测引擎：事件驱动、次bar开盘撮合、pandas 自实现指标、日线全量+分钟抽样回填验证（用户已确认四项决策）。

## Context

三期数据层完成（87 测试全绿）。设计文档留白方向 = 回测引擎。2026-08-30 探测：**分钟 K 权限现已可用**（sdk-notes §2 过时，深度限最近一年），WS 仍无权限。历史分钟回填（一年）可行，可补数据 + 供回测。

## Task 1: 指标库（indicators.py）

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

纯 pandas 向量化：`ma, ema, rsi(Wilder), macd(dif/dea/hist), kdj, atr, boll`。RSI/MACD 与教科书已知值对拍。

## Task 2: 策略接口 + 撮合（strategy.py / broker.py）

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

- `Strategy` 基类：`init(ctx) / on_bar(ctx) / on_finish(ctx)`
- `Context`：`symbols / bars / positions / cash / now / history(symbol) / buy / sell / close_position`
- `broker.py`：Order + 撮合（次bar开盘）+ 佣金 0.03% 双边最低5元 / 印花税卖出0.05% / 滑点0可配 + A股一手100取整 + T+1锁定 + 涨跌停（一字板顺延/收盘撤销）+ 现金不足降满仓或放弃

## Task 3: 回测引擎循环（engine.py）

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

- 预取：`dc.get_klines(symbol, period, start, end, adjust="forward")`
- `times` = 各标的时间戳并集排序；逐 t：`execute_pending(bars)` → `strategy.on_bar(ctx)`
- 无前视：t 时刻信号 t+1 开盘成交；`history` 不含未来
- 多标的共享资金池

## Task 4: 绩效统计（performance.py）

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 运行确认失败 → Step 3: 实现 → Step 4: 通过**

- 权益曲线（close 重估持仓）；总收益/年化/最大回撤/夏普（年化无风险=0）/胜率/交易次数/盈亏比/交易明细

## Task 5: 示例策略 + 真实 smoke

- [x] **Step 1: 实现双均线示例 + run_backtest.py**（单标的 + 多标的，打印绩效+权益曲线）
- [x] **Step 2: 真实数据跑通**（600000.SH 日线 + 多标的日线；分钟用回填后数据可选跑）
- [ ] **Step 3: Commit**

> 真实 smoke 顺带发现并修复 Phase 3 遗留 bug：`get_klines("1d")` 跨今日零点时误调
> `get_intraday("1d")`（接口不支持）-> 改为聚合当日 1m intraday 成一根日线 bar（时间戳=北京当日 0 点）。
> 已加回归测试 test_intraday.py::test_get_klines_daily_today_aggregates_from_intraday。

## Task 6: 真实回填验证（数据补全）

- [x] **Step 1: 更新 sdk-notes §2**（分钟权限已可用、深度限一年）
- [x] **Step 2: 日线全市场回填**（backfill.py，5555 标的，批量 60次/分）
- [x] **Step 3: 分钟抽样回填**（随机 3-5 只，1m/5m/15m/30m/60m 各一年）+ validate.py cross_check 真实生效
- [ ] **Step 4: Commit**

> 真实探测发现并修复分页 bug：服务端对 [start,end] 最多返回 5000 根（窗口内最近 5000 根），
> 原前向分页首页即撞 end_ms 提前 break，1m/5m 永远拿不到全年。改为**反向分页**
> （cursor 从 end_ms 逐页向旧翻，终止 = min_ts ≤ start_ms，不按页长判断——5m 每页只回 ~4980 根）。
> 修复后实测：1m 58k 根/年、5m 11.5k、15m 3.9k、30m 1.9k、60m 964，均覆盖 363 天。
> 测试 test_tickflow_client.py 分页用例同步改为反向语义。
>
> 日线全市场回填 `pending=0`（前几期已回填，幂等跳过）。backfill 新增 `--symbols` / `symbols` 参数供抽样。
>
> 分钟回填真实探测发现**令牌桶 bug**：`TokenBucket.capacity = rate`，rate<1（分钟批量档 0.5/s）时
> capacity 卡在 0.5，令牌永远凑不满 acquire 的 1.0 阈值 → 无限 sleep 睡死（回填 20 分钟零请求，
> 主线程一直 time_sleep）。修复：`capacity = max(1.0, rate)`，burst 至少 1 令牌；rate≥1 行为不变。
> 已加回归测试 test_ratelimit.py::test_rate_below_one_still_acquires。修复后分钟抽样回填 45s 完成，
> 1m 58,081 根/标的 ×4、5m/15m/30m/60m 与预期一致，validate.py cross_check 4 标的 1m 聚合 vs 1d 全部一致。

## Task 7: README + 全量回归

- [x] **Step 1: README 补充**（回测用法、指标、示例、回填说明、第三期 WS 权限状态）
- [x] **Step 2: `uv run pytest` 全量回归**（126 测试全绿）
- [ ] **Step 3: Commit**

> 全量回归发现并修复 test_daily_maintenance 的 fake 建模问题（反向分页的副作用）：
> 日终拉当日 bar 时窗口 [昨日+1, 今日] 取到今日 bar 后（min_ts>start）还会向旧探测一页，
> 对真实服务端该页返回空；但 fake 队列会误把下一标的的 df 当探测页返回。已在两标的的
> 数据后各补一个空探测页（模拟真实服务端行为）。代码本身对真实服务端正确，非代码 bug。

## 关键复用

- 数据：`DataCenter.get_klines`（前复权 forward）
- 测试：`tests/conftest.py` 的 FakeTickFlow / make_kline_df / FakeClock
- 交易日历（如需）：`src/datacenter/quality.py` 的 trading_calendar
