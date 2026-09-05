import { useState } from "react";
import KlineBrowser from "./pages/KlineBrowser";
import FactorBrowser from "./pages/FactorBrowser";

const TABS = [
  { key: "klines", label: "行情" },
  { key: "factors", label: "因子" },
] as const;

export default function App() {
  const [tab, setTab] = useState<string>("klines");

  return (
    <div className="shell">
      <header className="appbar">
        <div className="brand">
          <span className="brand-mark">K</span>
          <div className="brand-text">
            <span className="brand-name">本地行情终端</span>
            <span className="brand-sub">LOCAL MARKET TERMINAL</span>
          </div>
        </div>
        <nav className="tabnav">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={"tab" + (tab === t.key ? " active" : "")}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="content">
        {/* 两页都保持挂载（display 切换），切 tab 不丢已选标的/分页状态 */}
        <div style={{ display: tab === "klines" ? undefined : "none" }}>
          <KlineBrowser />
        </div>
        <div style={{ display: tab === "factors" ? undefined : "none" }}>
          <FactorBrowser />
        </div>
      </main>
    </div>
  );
}
