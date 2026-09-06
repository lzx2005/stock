import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUpRight,
  ChartLineUp,
  Flask,
  Pulse,
  ArrowRight,
} from "@phosphor-icons/react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { api } from "./api";
import KlineBrowser from "./pages/KlineBrowser";
import FactorBrowser from "./pages/FactorBrowser";
import MonitorBoard from "./pages/MonitorBoard";
import ResearchGuide from "./components/ResearchGuide";
import { Button } from "./components/Common";
type Tab = "market" | "factors" | "monitor";
const tabs = [
  { id: "market", name: "行情", en: "Market", icon: ChartLineUp },
  { id: "factors", name: "因子", en: "Factors", icon: Flask },
  { id: "monitor", name: "盯盘", en: "Monitor", icon: Pulse },
] as const;
export default function App() {
  const [tab, setTab] = useState<Tab>("market");
  const [connected, setConnected] = useState<boolean | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const workspace = useRef<HTMLElement>(null);
  const scrollers = useRef<Partial<Record<Tab, HTMLDivElement | null>>>({});
  const positions = useRef<Record<Tab, number>>({
    market: 0,
    factors: 0,
    monitor: 0,
  });
  useEffect(() => {
    const c = new AbortController();
    api("periods", {}, c.signal)
      .then(() => setConnected(true))
      .catch(() => {
        if (!c.signal.aborted) setConnected(false);
      });
    return () => c.abort();
  }, []);
  useGSAP(
    () => {
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches)
        gsap.from(".hero-enter", {
          y: 18,
          opacity: 0,
          duration: 0.8,
          stagger: 0.12,
          ease: "power3.out",
        });
    },
    { scope: root },
  );
  function navigate(next: Tab) {
    if (scrollers.current[tab])
      positions.current[tab] = scrollers.current[tab]!.scrollTop;
    setTab(next);
    requestAnimationFrame(() => {
      if (scrollers.current[next])
        scrollers.current[next]!.scrollTop = positions.current[next];
      workspace.current?.scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
        block: "start",
      });
    });
  }
  return (
    <div ref={root} className="app-root">
      <a href="#workspace" className="skip-link">
        跳至工作区
      </a>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="观澜 Stock 首页">
          <span className="brand-mark">
            <i />
            <i />
            <i />
            <i />
          </span>
          <strong>
            观澜<span>Stock</span>
          </strong>
        </a>
        <nav className="main-nav" aria-label="主要导航">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : ""}
              onClick={() => navigate(t.id)}
            >
              {t.name}
              <span>{t.en}</span>
            </button>
          ))}
        </nav>
        <div className="header-right">
          <span
            className={`connection ${connected === false ? "offline" : ""}`}
          >
            <i />
            {connected === null
              ? "连接中"
              : connected
                ? "本地服务已连接"
                : "本地服务未连接"}
          </span>
          <a href="#guide" className="header-guide">
            研究指南 <ArrowUpRight size={16} />
          </a>
        </div>
      </header>
      <main id="top" className="overflow-x-hidden w-full max-w-full">
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow hero-enter">
              INDEPENDENT THINKING. INFORMED DECISIONS.
            </span>
            <h1 className="max-w-6xl hero-enter">
              看见波动，
              <br />
              <span>也看见可能。</span>
            </h1>
            <p className="hero-enter">
              从行情到因子，从观察到行动。
              <br />
              为你的每一个交易想法，找到数据的依据。
            </p>
            <div className="hero-buttons hero-enter">
              <Button tone="dark" onClick={() => navigate("market")}>
                进入研究工作台 <ArrowUpRight size={19} />
              </Button>
              <a href="#guide" className="text-link">
                了解研究流程 <ArrowDown size={17} />
              </a>
            </div>
          </div>
          <div className="hero-art hero-enter" aria-hidden="true">
            <div className="art-grid" />
            <div className="art-orbit orbit-one" />
            <div className="art-orbit orbit-two" />
            <div className="art-orbit orbit-three" />
            <div className="art-core">
              <div className="art-bars">
                {[24, 42, 67, 45, 83, 58, 98, 76, 108, 90, 127, 110].map(
                  (h, i) => (
                    <i
                      key={i}
                      style={
                        {
                          height: h,
                          "--delay": `${i * 0.08}s`,
                        } as React.CSSProperties
                      }
                    />
                  ),
                )}
              </div>
            </div>
            <svg className="art-line" viewBox="0 0 500 270">
              <path
                d="M20 205 74 184 110 197 152 145 196 161 235 102 270 120 310 77 344 95 390 38 470 18"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <circle cx="470" cy="18" r="4" fill="currentColor" />
            </svg>
            <span className="art-caption">PERSPECTIVE CHANGES EVERYTHING.</span>
            <span className="art-coordinate">PRICE × TIME</span>
          </div>
        </section>
        <section id="workspace" ref={workspace} className="workspace">
          <div className="workspace-bar">
            <div
              className="workspace-tabs"
              role="tablist"
              aria-label="研究工作区"
            >
              {tabs.map((t) => (
                <button
                  key={t.id}
                  id={`tab-${t.id}`}
                  role="tab"
                  aria-selected={tab === t.id}
                  aria-controls={`panel-${t.id}`}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                      e.preventDefault();
                      const i = tabs.findIndex((t) => t.id === tab);
                      const next =
                        tabs[(i + (e.key === "ArrowRight" ? 1 : 2)) % 3].id;
                      navigate(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }
                  }}
                  tabIndex={tab === t.id ? 0 : -1}
                  className={tab === t.id ? "active" : ""}
                  onClick={() => navigate(t.id)}
                >
                  <t.icon size={20} />
                  {t.name}
                  <span>{t.en}</span>
                </button>
              ))}
            </div>
            <span className="workspace-note">
              YOUR RESEARCH, YOUR EDGE <ArrowRight size={15} />
            </span>
          </div>
          {tabs.map((t) => (
            <div
              key={t.id}
              ref={(el) => {
                scrollers.current[t.id] = el;
              }}
              id={`panel-${t.id}`}
              role="tabpanel"
              aria-labelledby={`tab-${t.id}`}
              hidden={tab !== t.id}
              className="page-scroll"
            >
              {t.id === "market" ? (
                <KlineBrowser active={tab === "market"} />
              ) : t.id === "factors" ? (
                <FactorBrowser />
              ) : (
                <MonitorBoard active={tab === "monitor"} />
              )}
            </div>
          ))}
        </section>
        <div id="guide">
          <ResearchGuide navigate={navigate} />
        </div>
      </main>
      <footer>
        <a href="#top" className="brand">
          <span className="brand-mark">
            <i />
            <i />
            <i />
            <i />
          </span>
          <strong>
            观澜<span>Stock</span>
          </strong>
        </a>
        <span>独立思考，让数据说话。</span>
        <div>
          <a href="#workspace">研究工作台</a>
          <a href="#guide">研究指南</a>
          <span>LOCAL FIRST.</span>
        </div>
      </footer>
    </div>
  );
}
