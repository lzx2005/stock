import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import dayjs from "dayjs";

export interface KlineBar {
  ts: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  amt: number;
}

const UP = "#E23B33";
const DOWN = "#0FA67C";

/** 简单均线（前端纯展示；MA 在回测/因子侧另有权威计算，这里只服务图表） */
function sma(bars: KlineBar[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c;
    if (i >= n) sum -= bars[i - n].c;
    out.push(i >= n - 1 ? +(sum / n).toFixed(3) : null);
  }
  return out;
}

function fmtAmt(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + " 万";
  return String(v);
}

export default function EChartsKline({ bars, isMinute }: { bars: KlineBar[]; isMinute: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chartRef.current = echarts.init(ref.current);
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;

    const labels = bars.map((b) =>
      isMinute ? dayjs(b.ts).format("MM-DD HH:mm") : dayjs(b.ts).format("YYYY-MM-DD")
    );
    const ma5 = sma(bars, 5);
    const ma10 = sma(bars, 10);
    const ma20 = sma(bars, 20);

    chart.setOption(
      {
        animation: false,
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross", label: { backgroundColor: "#1f2430" } },
          backgroundColor: "#1f2430",
          borderColor: "#000",
          textStyle: { color: "#fff", fontSize: 12 },
          formatter: (params: any) => {
            const ps = params as { dataIndex: number; axisValue: string }[];
            if (!ps.length) return "";
            const i = ps[0].dataIndex;
            const b = bars[i];
            const pct = b.o === 0 ? 0 : ((b.c - b.o) / b.o) * 100;
            const col = b.c >= b.o ? UP : DOWN;
            const row = (k: string, v: string, vColor?: string) =>
              `<div style="display:flex;justify-content:space-between;gap:22px">` +
              `<span style="color:#9aa4b2">${k}</span>` +
              `<span${vColor ? ` style="color:${vColor};font-weight:600"` : ""}>${v}</span></div>`;
            return [
              `<div style="font-weight:600;margin-bottom:4px">${ps[0].axisValue}</div>`,
              row("开", b.o.toFixed(2)),
              row("高", b.h.toFixed(2)),
              row("低", b.l.toFixed(2)),
              row("收", `${b.c.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)`, col),
              row("量", fmtAmt(b.v)),
              row("额", fmtAmt(b.amt)),
            ].join("");
          },
        },
        grid: [
          { left: 58, right: 16, top: 14, height: "56%" },
          { left: 58, right: 16, top: "70%", height: "16%" },
        ],
        xAxis: [
          {
            type: "category",
            data: labels,
            scale: true,
            boundaryGap: true,
            axisLine: { lineStyle: { color: "#c9d2dd" } },
            axisLabel: { color: "#5c6b7d", fontSize: 11 },
          },
          {
            type: "category",
            data: labels,
            scale: true,
            gridIndex: 1,
            boundaryGap: true,
            axisLine: { lineStyle: { color: "#c9d2dd" } },
            axisLabel: { show: false },
            axisTick: { show: false },
          },
        ],
        yAxis: [
          {
            scale: true,
            axisLabel: { color: "#5c6b7d", fontSize: 11 },
            splitLine: { lineStyle: { color: "#edf1f6" } },
          },
          {
            scale: true,
            gridIndex: 1,
            splitNumber: 2,
            axisLabel: { color: "#5c6b7d", fontSize: 10, formatter: (v: number) => fmtAmt(v) },
            splitLine: { show: false },
          },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1], start: 30, end: 100 },
          {
            type: "slider", xAxisIndex: [0, 1], start: 30, end: 100,
            bottom: 4, height: 16, borderColor: "#e4e9f0",
            fillerColor: "rgba(49,69,107,0.12)",
            handleStyle: { color: "#31456b" },
          },
        ],
        series: [
          {
            name: "K线",
            type: "candlestick",
            data: bars.map((b) => [b.o, b.c, b.l, b.h]),
            itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
          },
          { name: "MA5", type: "line", data: ma5, symbol: "none", smooth: true, lineStyle: { width: 1.2, color: "#d9a400" } },
          { name: "MA10", type: "line", data: ma10, symbol: "none", smooth: true, lineStyle: { width: 1.2, color: "#4c7bd9" } },
          { name: "MA20", type: "line", data: ma20, symbol: "none", smooth: true, lineStyle: { width: 1.2, color: "#c77fbf" } },
          {
            name: "成交量",
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: bars.map((b) => b.v),
            itemStyle: { color: (p: any) => (bars[p.dataIndex].c >= bars[p.dataIndex].o ? UP : DOWN) },
          },
        ],
      },
      true
    );
  }, [bars, isMinute]);

  return <div ref={ref} className="kchart" />;
}
