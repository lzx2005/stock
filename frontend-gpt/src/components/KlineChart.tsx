import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { CandlestickChart, LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { Bar } from "../types";
import { dateLabel, movingAverage } from "../domain";
echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  CanvasRenderer,
]);
export default function KlineChart({
  rows,
  period,
  active,
}: {
  rows: Bar[];
  period: string;
  active: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!host.current) return;
    chart.current = echarts.init(host.current);
    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(host.current);
    return () => {
      resize.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    const labels = rows.map((r) => dateLabel(r[0], period.endsWith("m")));
    chart.current?.setOption(
      {
        animation: false,
        backgroundColor: "transparent",
        textStyle: { fontFamily: "Outfit, sans-serif" },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross" },
          confine: true,
        },
        legend: {
          top: 0,
          left: 16,
          icon: "roundRect",
          itemWidth: 14,
          itemHeight: 3,
          textStyle: { color: "#72796e", fontSize: 11 },
          data: ["MA5", "MA10", "MA20"],
        },
        grid: [
          { left: 58, right: 24, top: 44, height: "58%" },
          { left: 58, right: 24, top: "74%", height: "13%" },
        ],
        xAxis: [0, 1].map((i) => ({
          type: "category",
          gridIndex: i,
          data: labels,
          boundaryGap: true,
          axisLine: { lineStyle: { color: "#dfe2d9" } },
          axisTick: { show: false },
          axisLabel: { show: i === 1, color: "#92988c", fontSize: 10 },
          splitLine: { show: false },
        })),
        yAxis: [0, 1].map((i) => ({
          scale: true,
          gridIndex: i,
          splitNumber: i ? 2 : 4,
          axisLabel: {
            color: "#92988c",
            fontSize: 10,
            formatter: i
              ? (v: number) => (v >= 1e4 ? `${(v / 1e4).toFixed(0)}万` : v)
              : undefined,
          },
          splitLine: { lineStyle: { color: "#e9ebe4", type: "dashed" } },
        })),
        dataZoom: [
          {
            type: "inside",
            xAxisIndex: [0, 1],
            start: Math.max(0, 100 - (100 * 90) / rows.length),
            end: 100,
          },
          {
            type: "slider",
            xAxisIndex: [0, 1],
            bottom: 0,
            height: 18,
            borderColor: "transparent",
            backgroundColor: "#f0f2e9",
            fillerColor: "#c8d8a84d",
            handleStyle: { color: "#85946e", borderColor: "#85946e" },
            dataBackground: {
              lineStyle: { color: "#adba9b" },
              areaStyle: { color: "#d7dfca" },
            },
          },
        ],
        series: [
          {
            type: "candlestick",
            name: "K线",
            data: rows.map((r) => [r[1], r[4], r[3], r[2]]),
            itemStyle: {
              color: "#ca5b50",
              color0: "#38876f",
              borderColor: "#ca5b50",
              borderColor0: "#38876f",
            },
          },
          ...[5, 10, 20].map((n, i) => ({
            type: "line",
            name: `MA${n}`,
            data: movingAverage(
              rows.map((r) => r[4]),
              n,
            ),
            showSymbol: false,
            lineStyle: {
              width: 1.3,
              color: ["#b2994c", "#9383bb", "#7194b9"][i],
            },
            itemStyle: { color: ["#b2994c", "#9383bb", "#7194b9"][i] },
          })),
          {
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            name: "成交量",
            data: rows.map((r) => ({
              value: r[5],
              itemStyle: { color: r[4] >= r[1] ? "#ca5b5080" : "#38876f80" },
            })),
          },
        ],
      },
      true,
    );
  }, [rows, period]);
  useEffect(() => {
    if (active) requestAnimationFrame(() => chart.current?.resize());
  }, [active]);
  return (
    <div
      className="chart"
      ref={host}
      role="img"
      aria-label={`${rows.length} 根 ${period} K线，包含 MA5、MA10、MA20 和成交量`}
    />
  );
}
