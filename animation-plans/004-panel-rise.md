# 004 — 下钻/详情面板入场（fade + 轻微上浮）

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: MEDIUM（missed opportunity，additive）
- **Category**: Missed opportunities
- **Estimated scope**: 1 file（frontend/src/style.css），~15 行
- **Depends on**: 001（`--ease-out` token）

## Problem

因子页点行下钻（因子→目录→组合→值）和行情页选中标的时，下级面板瞬间凭空出现（`{selFactor && <div className="panel">…}` 条件渲染），没有运动解释"它从哪来"。空间一致性原则：入场应有一个短促的 fade+rise。

## Target

新 keyframes + 两个入口选择器，全部在既有 `prefers-reduced-motion: no-preference` 媒体块内：

```css
@keyframes panel-rise {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: none; }
}
.fb > .panel { animation: panel-rise 200ms var(--ease-out); }
.kb-detail { animation: panel-rise 200ms var(--ease-out); }
```

- 200ms 在 AUDIT.md「dropdowns/selects 150-250ms」预算内；translateY(6px) 克制，不用大位移
- reduced-motion 下完全静止（面板直接出现）——这符合"去掉位移、保留即时性"

## Repo conventions to follow

- 参照既有 panel-in（style.css:199-200）的写法与门控
- 只加 CSS：tsx 的条件渲染天然会在挂载时触发入场动画，无需改组件

## Steps

1. 在 `prefers-reduced-motion: no-preference` 媒体块内追加 `panel-rise` keyframes 与上述两条规则
2. 确认与 `.content > div { animation: panel-in ... }` 不冲突（kb-detail 在 content 内层，两个 animation 是不同元素，可叠加）

## Boundaries

- 只动 `frontend/src/style.css`；不改任何 tsx
- 不给 `.panel` 加 stagger delay（下钻一次只出现一个面板，级联延迟反而拖慢）
- 不动盯盘页（.mb 面板常驻，非条件出现，不需要入场）

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过
- **Feel check**: 因子页连续点三级下钻——每级面板 200ms 淡入微浮；行情页点列表行——右侧详情区同样入场；动画期间点击立即可交互（不被动画阻塞）；reduced-motion 下直接出现
- **Done when**: 面板出现不再是瞬时硬切，且 200ms 内完成
