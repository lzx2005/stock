# 001 — 收敛缓动/时长为共享 token

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: LOW
- **Category**: Cohesion & tokens
- **Estimated scope**: 1 file（frontend/src/style.css），~10 行

## Problem

缓动与时长散落硬编码：`style.css:83` `transform 100ms ease-out`、`:109` `width 0.2s ease`、`:118` 同 83、`:175` `background 0.15s`、`:199-200` `160ms ease-out`、`:207` `1.6s ease-in-out`。曲线各不相同且无名，后续改动无法保持一致。

## Target

`:root` 新增三个 token（取自 AUDIT.md 标准值，禁止近似）：

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);        /* strong ease-out for UI */
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);    /* on-screen movement */
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);     /* iOS-like drawer curve */
```

替换点：
- `:83`、`:118` → `transform 100ms var(--ease-out)`（:active 按压反馈）
- `:199` panel-in → `animation: panel-in 160ms var(--ease-out)`
- `:175` 表格行 hover `background 0.15s` 保持 `ease`（AUDIT.md：hover/颜色变化用 ease），不改
- lamp-pulse 的 `ease-in-out`（:207）→ `var(--ease-in-out)`
- `:109` 的 width 过渡由计划 002 处理，本计划不动

## Repo conventions to follow

- 现有 token 全部在 `frontend/src/style.css :root`（如 `--up: #f0453c`、`--radius: 2px`），新 token 放同一区块
- 参考 `style.css:199-200` 的 panel-in：动画一律门控在 `@media (prefers-reduced-motion: no-preference)` 内

## Steps

1. `style.css :root` 末尾（`--mono` 之后）追加上述三个 `--ease-*` 变量
2. 按"替换点"逐处替换为 var() 引用

## Boundaries

- 只动 `frontend/src/style.css`
- 不改任何时长数值，只把曲线换成 token
- 不新增依赖；不动 tsx

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过
- **Feel check**: 按压 tab/折叠条，手感应与改前一致或更利落；盯盘灯呼吸节奏不变
- **Done when**: style.css 中除 AUDIT.md 豁免处（hover ease、lamp 循环）外不再出现裸 `ease-out`/`ease-in-out` 字面量
