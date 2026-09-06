# Animation Plans — 前端盯盘终端

来源：`/improve-animations 加上动画` 审计（2026-09-05，commit 271b6b0）。用户已确认全部执行。

| # | 标题 | 级别 | 状态 |
|---|---|---|---|
| 001 | 收敛缓动/时长为共享 token | LOW | DONE |
| 002 | 左栏折叠去掉 width 布局动画 | MEDIUM | DONE |
| 003 | 报价价格更新闪烁（涨红/跌绿） | MEDIUM | DONE |
| 004 | 下钻/详情面板入场 fade+rise | MEDIUM | DONE |
| 005 | 盯盘灯翻转 glow burst | LOW | DONE |
| 006 | 信号历史最新行入场高亮 | LOW | DONE |

**执行顺序**：001 → 002 → 003 → 004 → 005 → 006（001 提供 `--ease-*` token，其余全部依赖它；其余互相独立）。

**共同约束**：纯 CSS/React 状态实现，不引动画库；所有新动画门控 `prefers-reduced-motion`；涨跌红绿仅用于涨跌语义，盯盘语境用琥珀。
