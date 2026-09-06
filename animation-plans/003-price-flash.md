# 003 — 报价价格更新闪烁（涨红/跌绿底色短闪）

- **Status**: DONE
- **Commit**: 271b6b0
- **Severity**: MEDIUM（missed opportunity，additive）
- **Category**: Missed opportunities
- **Estimated scope**: 2 files（frontend/src/pages/KlineBrowser.tsx ~15 行；frontend/src/style.css ~20 行）
- **Depends on**: 001（`--ease-out` token）

## Problem

`KlineBrowser.tsx` 中点击「取最新」或选中标的回源后，报价带的价格/涨跌幅瞬间换新值，用户无法感知"价格变了、往哪边变了"。专业终端的标准语言是：新价到达时按变动方向给一次底色短闪。

当前代码（KlineBrowser.tsx 报价带，约 185-188 行）：

```tsx
<span className="quote-price" style={{ color: col }}>{latest.c.toFixed(2)}</span>
<span className="quote-pct" style={{ color: col }}>
```

## Target

- 用 `useRef` 记录上一次 latest 收盘价；`useEffect` 监听 `latest?.c`：有前值且发生变化时，设置 `flash` 状态（`"up" | "down"`，方向 = 新价 vs 前价；同价不闪），450ms 后清除
- 首次选中（无前值）不闪；仅「取最新」/换标的回源后真实变化才闪
- CSS 两个一次性 keyframes（闪烁的是背景，不动位置）：

```css
@media (prefers-reduced-motion: no-preference) {
  .quote-price.flash-up   { animation: price-flash-up 450ms var(--ease-out); }
  .quote-price.flash-down { animation: price-flash-down 450ms var(--ease-out); }
  @keyframes price-flash-up {
    from { background: rgba(240, 69, 60, 0.3); } to { background: transparent; }
  }
  @keyframes price-flash-down {
    from { background: rgba(23, 184, 144, 0.3); } to { background: transparent; }
  }
}
```

- `.quote-price` 加 `border-radius: var(--radius); padding: 0 4px;` 让底色闪有形状（shape lock 2px）

## Repo conventions to follow

- 涨跌色用既有变量 `var(--up)`/`var(--down)` 的 rgba 形式（UP #F0453C / DOWN #17B890）
- 动画一律 `prefers-reduced-motion: no-preference` 门控（参照 style.css:199）
- 组件内状态用 useState/useRef，不引第三方动画库

## Steps

1. style.css：`.quote-price` 加 radius/padding；追加上述 flash keyframes（放 panel-in 同一媒体块内）
2. KlineBrowser.tsx：加 `const prevCloseRef = useRef<number | undefined>(undefined);` 和 `const [flash, setFlash] = useState<"up" | "down" | null>(null);`
3. `useEffect(() => { ... }, [latest?.c])`：比较 prevCloseRef，变化则 setFlash + `setTimeout(() => setFlash(null), 450)`（effect cleanup 里 clearTimeout），最后更新 ref
4. 价格 span：`className={"quote-price" + (flash ? ` flash-${flash}` : "")}`

## Boundaries

- 不动 EChartsKline.tsx；不改取数/回源逻辑
- 闪烁只在价格 span 上，不要闪整个报价带
- 同价刷新不闪；换标的（latest 从 undefined 到新值）不闪

## Verification

- **Mechanical**: `cd frontend && npm run build` 通过（tsc 无错）
- **Feel check**: 选中一只票 → 点「取最新」，若价格有变，价格区按方向红/绿短闪一次后消退；DevTools Animations 面板 10% 慢放确认只动背景色；Rendering 面板开 reduced-motion 后闪烁消失、数值仍正常更新
- **Done when**: 连续点「取最新」不会叠加/卡死动画（timeout 被 cleanup 清理）
