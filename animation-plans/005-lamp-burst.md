# 005 — 盯盘灯翻转：颜色过渡 + 点亮瞬间一次性 glow burst

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: LOW（missed opportunity，additive）
- **Category**: Missed opportunities
- **Estimated scope**: 1 file（frontend/src/style.css），~15 行
- **Depends on**: 001（`--ease-out` / `--ease-in-out` token）

## Problem

盯盘页任务的买入/卖出灯（antd Badge status dot）在灰↔琥珀之间瞬时硬切（`MonitorBoard.tsx:146`、`:157`，`Badge status={v ? "warning" : "default"}`）。灯的"点亮"是本系统最重要的状态时刻（边沿触发即推送），值得一个一次性强调。

当前 CSS（style.css:206-215）只有常亮后的无限 lamp-pulse，点亮瞬间无过渡。

## Target

```css
/* 灰↔琥珀颜色本身平滑过渡（hover/颜色规则用 ease 的强化版 ease-out） */
.mb .ant-badge-status-dot {
  transition: background-color 200ms var(--ease-out), box-shadow 200ms var(--ease-out);
}

/* 点亮瞬间：一次性 burst，然后交接给既有 lamp-pulse 呼吸 */
@media (prefers-reduced-motion: no-preference) {
  .mb .ant-badge-status-warning .ant-badge-status-dot {
    animation: lamp-burst 400ms var(--ease-out) 1,
               lamp-pulse 1.6s var(--ease-in-out) 400ms infinite;
  }
  @keyframes lamp-burst {
    0%   { box-shadow: 0 0 0 rgba(232, 163, 61, 0); }
    40%  { box-shadow: 0 0 14px rgba(232, 163, 61, 1); }
    100% { box-shadow: 0 0 6px rgba(232, 163, 61, 0.9); }
  }
}
```

- 替换现有 `.mb .ant-badge-status-warning .ant-badge-status-dot { box-shadow: ...; animation: lamp-pulse ... }` 规则（burst 末帧 = pulse 的常态阴影，无缝交接）
- 琥珀色值 = 既有 `--amber` #E8A33D（rgba 232,163,61）
- 既有 `@media (prefers-reduced-motion: reduce)` 里 `animation: none` 的规则要覆盖新选择器（保持，确认生效即可）

## Repo conventions to follow

- lamp-pulse（style.css:207-212）即既有模式：语义状态灯 + reduced-motion 门控
- 用 001 的 token，不写裸 cubic-bezier

## Steps

1. 加 `.mb .ant-badge-status-dot` 的 transition 规则
2. 改写 warning dot 规则为 burst + pulse 双动画，加 lamp-burst keyframes
3. 确认 reduce 媒体查询仍命中（`.mb .ant-badge-status-warning .ant-badge-status-dot { animation: none; }` 无需改）

## Boundaries

- 只动 style.css；不改 MonitorBoard.tsx
- 不改变灯的颜色语义（琥珀=亮、灰=灭），只加"瞬间"
- burst 只放一次（`1`），不要循环

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过
- **Feel check**: 盯盘页切换任务启用/等灯翻转（或本地改库翻转 buy_on 后刷新）：灯灭→亮时先爆一下辉光（400ms）再进入 1.6s 呼吸；亮→灭时 200ms 平滑变灰；reduced-motion 下只有颜色瞬时切换、无任何动画
- **Done when**: burst 只播放一次，之后呼吸节奏与改前一致
