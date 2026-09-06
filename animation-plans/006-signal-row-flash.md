# 006 — 信号历史最新行入场高亮

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: LOW（missed opportunity，additive）
- **Category**: Missed opportunities
- **Estimated scope**: 2 files（frontend/src/pages/MonitorBoard.tsx ~3 行；frontend/src/style.css ~12 行）
- **Depends on**: 001（`--ease-out` token）

## Problem

盯盘页信号历史表刷新/选中任务后，最新信号行与其他行无区分，用户要自己对时间找"哪条是新的"。后端 `MonitorStore.list_signals`（src/monitor/store.py:130-140）按 `ts DESC, id DESC` 返回——**首行即最新**，可直接用行索引定位。

当前（MonitorBoard.tsx:250-258）信号 Table 无 rowClassName。

## Target

- MonitorBoard.tsx 信号表加 `rowClassName={(_, i) => (i === 0 ? "sig-new" : "")}`
- style.css（no-preference 媒体块内）：

```css
@media (prefers-reduced-motion: no-preference) {
  .sig-new td { animation: sig-flash 900ms var(--ease-out); }
  @keyframes sig-flash {
    from { background: rgba(232, 163, 61, 0.18); }  /* 琥珀淡底 = 盯盘语义色 --amber */
    to   { background: transparent; }
  }
}
```

- 900ms：比 price-flash 长（这是"看一眼历史"的场景，不是高频操作），仍远低于循环动画
- 只染背景不动布局；分页翻页时首行也会闪一次（可接受——每页"本页最新"）

## Repo conventions to follow

- 行级动画加在 `td` 上（tr 背景在 antd 里由 td 承载），参照 `.row-selected td`（style.css:178）
- 盯盘语境用琥珀（--amber），不用红绿（涨跌语义避让，FRONTEND.md 硬规则）

## Steps

1. MonitorBoard.tsx：信号 Table 加 rowClassName（注意与任务表已有的 selTask rowClassName 互不干扰——只动信号表）
2. style.css：no-preference 媒体块内追加 sig-flash

## Boundaries

- 不动任务表；不改 signals 数据加载逻辑
- 不做"新增行检测"（无需 diff，首行高亮即可）
- 琥珀浓度不超 0.18，避免与 row-selected 的红色 0.1 底混淆

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过
- **Feel check**: 盯盘页点任务行/点刷新——信号表首行琥珀淡底 900ms 消退；翻页同样生效；reduced-motion 下无动画
- **Done when**: 每次信号表数据刷新，用户视线能被引导到最新一条
