# 002 — 左栏折叠去掉 width 布局动画

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: MEDIUM
- **Category**: Performance
- **Estimated scope**: 1 file（frontend/src/style.css），~5 行
- **Depends on**: 001（使用 `--ease-out` token 与 panel-in 既有模式）

## Problem

`style.css:109`：`.kb-list` 用 `transition: width 0.2s ease` 做折叠/展开。width 是布局属性，动画每一帧都触发内部 antd Table 重排重绘（非合成器属性），折叠瞬间可能掉帧。

```css
/* style.css:109 — current */
.kb-list { ... overflow: auto; transition: width 0.2s ease; }
```

## Target

瞬时切换宽度（布局跳变可接受，因为是用户主动点击的明确动作），内容层用透明度+轻微上浮做入场补偿（复用 panel-in 模式）：

```css
/* style.css */
.kb-list { ... overflow: auto; }   /* 删除 transition: width */

/* 与 panel-in 同一 media 门控块内追加 */
@media (prefers-reduced-motion: no-preference) {
  .kb-list:not(.collapsed) { animation: panel-in 200ms var(--ease-out); }
}
```

（`panel-in` keyframes 已在 style.css:200 定义，直接复用，不重复定义。）

## Repo conventions to follow

- 既有入场动画 `panel-in`（`style.css:199-200`）就是这个模式：opacity 淡入 + reduced-motion 门控
- token 用 001 引入的 `--ease-out`

## Steps

1. 删除 `.kb-list` 上的 `transition: width 0.2s ease`
2. 在 `prefers-reduced-motion: no-preference` 媒体块内加 `.kb-list:not(.collapsed)` 的 panel-in 入场

## Boundaries

- 只动 `frontend/src/style.css`；不改 KlineBrowser.tsx 的折叠逻辑/类名
- 不要引入 clip-path 或 JS 测量——保持简单

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过
- **Feel check**: 选中标的后点折叠按钮：宽度即刻到位、内容 200ms 淡入，无表格逐帧挤压感；反复快速点折叠/展开无动画堆积
- **Done when**: style.css 全文不再有 `transition: width`
