import { useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  ChartLineUp,
  Flask,
  Pulse,
} from "@phosphor-icons/react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
gsap.registerPlugin(useGSAP, ScrollTrigger);
const chapters = [
  {
    name: "观察行情",
    en: "Observe.",
    text: "价格是结果，量能是线索。把 K 线、均线与成交量放在一起，重新理解每一次波动。",
    icon: ChartLineUp,
    tab: "market",
  },
  {
    name: "拆解因子",
    en: "Understand.",
    text: "从趋势、动量到波动，把模糊的交易直觉，拆解成可以重复验证的条件。",
    icon: Flask,
    tab: "factors",
  },
  {
    name: "守候信号",
    en: "Stay ready.",
    text: "定义你的观察条件，让盯盘持续运行。在条件翻转的时刻，收到清晰的信号。",
    icon: Pulse,
    tab: "monitor",
  },
] as const;
export default function ResearchGuide({
  navigate,
}: {
  navigate: (tab: "market" | "factors" | "monitor") => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(0);
  const [slide, setSlide] = useState(0);
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(
          ".reveal-word",
          { opacity: 0.14 },
          {
            opacity: 1,
            stagger: 0.12,
            ease: "none",
            scrollTrigger: {
              trigger: ".research-statement",
              start: "top 85%",
              end: "bottom 40%",
              scrub: true,
            },
          },
        );
        gsap
          .timeline({
            scrollTrigger: {
              trigger: ".landscape",
              start: "top bottom",
              end: "bottom top",
              scrub: true,
            },
          })
          .fromTo(
            ".landscape-image",
            { scale: 0.8, opacity: 0.5 },
            { scale: 1, opacity: 1, duration: 1 },
          )
          .to(".landscape-image", {
            opacity: 0.2,
            filter: "grayscale(1) brightness(0.5)",
            duration: 1,
          });
      });
      return () => mm.revert();
    },
    { scope: root },
  );
  return (
    <div className="research-guide" ref={root}>
      <div className="marquee" aria-hidden="true">
        <div>
          {[0, 1, 2, 3].map((n) => (
            <span key={n}>
              LESS NOISE <i /> MORE SIGNAL <i /> BETTER QUESTIONS <i />
            </span>
          ))}
        </div>
      </div>
      <section className="research-story">
        <div className="story-heading">
          <span className="eyebrow">A CLEARER PERSPECTIVE</span>
          <h2>
            少一点噪声，
            <br />
            多一点洞察。
          </h2>
        </div>
        <p className="research-statement">
          {[
            "不急于",
            "寻找答案，",
            "先学会",
            "提出问题。",
            "用数据",
            "检验直觉，",
            "让每一次",
            "观察，",
            "都有迹可循。",
          ].map((word, i) => (
            <span className="reveal-word" key={i}>
              {word}
            </span>
          ))}
        </p>
      </section>
      <section
        className="guide-grid"
        aria-label="研究流程"
        style={{
          gridTemplateColumns: chapters
            .map((_, i) => (open === i ? "6fr" : "3fr"))
            .join(" "),
        }}
      >
        {chapters.map((chapter, i) => (
          <article
            key={chapter.tab}
            className={`guide-card ${open === i ? "expanded" : ""}`}
            onMouseEnter={() => setOpen(i)}
            onFocus={() => setOpen(i)}
          >
            <chapter.icon size={28} weight="thin" />
            <h3>{chapter.en}</h3>
            <button
              className="guide-title"
              onClick={() => {
                setOpen(i);
                navigate(chapter.tab);
              }}
            >
              {chapter.name}
              <ArrowUpRight size={22} />
            </button>
            <p>{chapter.text}</p>
          </article>
        ))}
      </section>
      <section className="perspective">
        <div className="landscape">
          <img
            className="landscape-image"
            src="https://picsum.photos/seed/mountain-perspective/1920/1080"
            alt="黑白山野与远方景色"
            loading="lazy"
            onError={(e) => {
              if (!e.currentTarget.src.endsWith("/landscape.svg"))
                e.currentTarget.src = "/landscape.svg";
            }}
          />
          <div className="landscape-overlay">
            <span>SEE THE BIGGER PICTURE.</span>
            <p>
              视野放远，
              <br />
              判断更清晰。
            </p>
          </div>
        </div>
        <div className="guide-carousel">
          <span className="eyebrow">研究手记</span>
          <span className="quote-mark">“</span>
          <h3 key={slide}>
            {
              [
                "从价格出发，\n回到条件本身。",
                "一个因子，\n一种观察市场的方式。",
                "信号值得等待，\n规则值得坚持。",
              ][slide]
            }
          </h3>
          <p>{chapters[slide].text}</p>
          <div>
            <span className="carousel-position">
              {String(slide + 1).padStart(2, "0")} <i>/ 03</i>
            </span>
            <button
              aria-label="上一条研究手记"
              onClick={() => setSlide((slide + 2) % 3)}
            >
              <ArrowLeft size={20} />
            </button>
            <button
              aria-label="下一条研究手记"
              onClick={() => setSlide((slide + 1) % 3)}
            >
              <ArrowRight size={20} />
            </button>
          </div>
        </div>
      </section>
      <section className="final-action">
        <span className="eyebrow">MAKE ROOM FOR YOUR NEXT IDEA</span>
        <button onClick={() => navigate("market")}>
          下一次洞察，
          <br />
          <span>从这里开始。</span>
          <ArrowUpRight weight="thin" />
        </button>
      </section>
    </div>
  );
}
