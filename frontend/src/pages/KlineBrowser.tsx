import { useCallback, useEffect, useState } from "react";
import { Button, DatePicker, Empty, Input, message, Select, Space, Table, Tooltip } from "antd";
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api, CoverageRow, KlinesResp, KlineRow } from "../api";
import EChartsKline, { KlineBar } from "../components/EChartsKline";

const PAGE_SIZE = 50;
const CHART_MAX = 2000;
const MINUTE_PERIODS = new Set(["1m", "5m", "15m", "30m", "60m"]);
const UP = "#E23B33";
const DOWN = "#0FA67C";

function fmt(ms: number, minute: boolean) {
  return minute ? dayjs(ms).format("YYYY-MM-DD HH:mm") : dayjs(ms).format("YYYY-MM-DD");
}
function fmtNum(v: number) {
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtAmt(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + " 万";
  return String(v);
}

export default function KlineBrowser() {
  const [periods, setPeriods] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState("");
  const [covPage, setCovPage] = useState(1);
  const [coverage, setCoverage] = useState<{ total: number; items: CoverageRow[] } | null>(null);
  const [covLoading, setCovLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const [selected, setSelected] = useState<CoverageRow | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [chartBars, setChartBars] = useState<KlineBar[]>([]);
  const [klines, setKlines] = useState<KlinesResp | null>(null);
  const [kLoading, setKLoading] = useState(false);
  const [kPage, setKPage] = useState(1);
  const [kSize, setKSize] = useState(PAGE_SIZE);

  useEffect(() => {
    api.periods().then((r) => setPeriods(r.items)).catch((e) => message.error(String(e.message)));
  }, []);

  const loadCoverage = useCallback((page: number, qv: string, pv: string) => {
    setCovLoading(true);
    api.coverage(qv, pv, page, PAGE_SIZE)
      .then((r) => { setCoverage(r); setCovPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setCovLoading(false));
  }, []);
  useEffect(() => { loadCoverage(1, q, period); }, [q, period, loadCoverage]);

  const loadKlines = useCallback((row: CoverageRow, page: number, size: number, rng: [number, number] | null) => {
    setKLoading(true);
    const [s, e] = rng ?? [row.start_ms, row.end_ms];
    api.klines(row.symbol, row.period, s, e, page, size)
      .then((r) => { setKlines(r); setKPage(page); setKSize(size); })
      .catch((err) => message.error(String(err.message)))
      .finally(() => setKLoading(false));
  }, []);

  const loadChart = useCallback((row: CoverageRow, rng: [number, number] | null) => {
    const [s, e] = rng ?? [row.start_ms, row.end_ms];
    api.klines(row.symbol, row.period, s, e, 1, CHART_MAX)
      .then((r) =>
        setChartBars(r.rows.map(([ts, o, h, l, c, v, amt]) => ({ ts, o, h, l, c, v, amt })))
      )
      .catch((err) => message.error(String(err.message)));
  }, []);

  const selectRow = (row: CoverageRow) => {
    setSelected(row);
    setCollapsed(false);
    setRange(null);
    setKlines(null);
    setChartBars([]);
    loadKlines(row, 1, PAGE_SIZE, null);
    loadChart(row, null);
  };

  const minute = selected ? MINUTE_PERIODS.has(selected.period) : false;
  const latest = chartBars[chartBars.length - 1];

  const covCols: ColumnsType<CoverageRow> = [
    { title: "代码", dataIndex: "symbol", className: "col-mono" },
    { title: "名称", dataIndex: "name", render: (v: string | null) => v ?? "-", ellipsis: true },
    { title: "周期", dataIndex: "period" },
    { title: "截止", dataIndex: "end_ms", render: (v: number, r) => fmt(v, MINUTE_PERIODS.has(r.period)) },
  ];

  const kCols: ColumnsType<KlineRow> = [
    { title: "时间", render: (_, r) => fmt(r[0], minute), className: "col-mono" },
    { title: "开", align: "right", className: "col-num", render: (_, r) => fmtNum(r[1]) },
    { title: "高", align: "right", className: "col-num", render: (_, r) => fmtNum(r[2]) },
    { title: "低", align: "right", className: "col-num", render: (_, r) => fmtNum(r[3]) },
    {
      title: "收", align: "right", className: "col-num",
      render: (_, r) => <span style={{ color: r[4] >= r[1] ? UP : DOWN }}>{fmtNum(r[4])}</span>,
    },
    { title: "量", align: "right", className: "col-num", render: (_, r) => fmtAmt(r[5]) },
    { title: "额", align: "right", className: "col-num", render: (_, r) => fmtAmt(r[6]) },
  ];

  return (
    <div className="kb">
      <aside className={"kb-list" + (collapsed ? " collapsed" : "")}>
        {collapsed ? (
          <div className="kb-collapsed" onClick={() => setCollapsed(false)} title="展开列表">
            <MenuUnfoldOutlined style={{ fontSize: 16 }} />
            <span>展开</span>
          </div>
        ) : (
          <>
            <div className="kb-toolbar">
              <Input.Search
                placeholder="搜索代码/名称"
                allowClear
                onSearch={(v) => setQ(v.trim())}
                size="small"
                style={{ flex: 1, minWidth: 140 }}
              />
              <Select
                placeholder="周期"
                allowClear
                size="small"
                style={{ width: 96 }}
                value={period || undefined}
                onChange={(v) => setPeriod(v ?? "")}
                options={periods.map((p) => ({ value: p, label: p }))}
              />
              {selected && (
                <Tooltip title="收起列表">
                  <Button
                    type="text"
                    size="small"
                    icon={<MenuFoldOutlined />}
                    onClick={() => setCollapsed(true)}
                  />
                </Tooltip>
              )}
            </div>
            <Table
              rowKey={(r) => `${r.symbol}|${r.period}`}
              size="small"
              loading={covLoading}
              dataSource={coverage?.items ?? []}
              columns={covCols}
              scroll={{ x: 400 }}
              rowClassName={(r) =>
                selected?.symbol === r.symbol && selected?.period === r.period ? "row-selected" : ""
              }
              onRow={(r) => ({ onClick: () => selectRow(r), style: { cursor: "pointer" } })}
              pagination={{
                current: covPage,
                pageSize: PAGE_SIZE,
                total: coverage?.total ?? 0,
                showSizeChanger: false,
                showTotal: (t) => `共 ${t} 条`,
                onChange: (p) => loadCoverage(p, q, period),
              }}
            />
          </>
        )}
      </aside>

      {selected && (
        <section className="kb-detail">
          <div className="quote-bar">
            <div className="quote-id">
              <span className="quote-symbol">{selected.symbol}</span>
              <span className="quote-name">{selected.name ?? selected.code ?? ""}</span>
              <span className="quote-period">{selected.period}</span>
            </div>
            <div className="quote-stats">
              {latest ? (() => {
                const pct = latest.o === 0 ? 0 : ((latest.c - latest.o) / latest.o) * 100;
                const col = latest.c >= latest.o ? UP : DOWN;
                const sign = pct >= 0 ? "▲" : "▼";
                return (
                  <>
                    <span className="quote-price" style={{ color: col }}>{latest.c.toFixed(2)}</span>
                    <span className="quote-pct" style={{ color: col }}>
                      {sign} {Math.abs(pct).toFixed(2)}%
                    </span>
                    <span className="quote-k">开<b>{fmtNum(latest.o)}</b></span>
                    <span className="quote-k">高<b>{fmtNum(latest.h)}</b></span>
                    <span className="quote-k">低<b>{fmtNum(latest.l)}</b></span>
                    <span className="quote-k">量<b>{fmtAmt(latest.v)}</b></span>
                    <span className="quote-k">额<b>{fmtAmt(latest.amt)}</b></span>
                  </>
                );
              })() : (
                <span className="quote-empty">该区间无数据</span>
              )}
            </div>
          </div>

          <div className="kb-filters">
            <Space wrap size="small">
              <DatePicker.RangePicker
                size="small"
                onChange={(dates) => {
                  const rng =
                    dates && dates[0] && dates[1]
                      ? [dates[0].startOf("day").valueOf(), dates[1].endOf("day").valueOf()] as [number, number]
                      : null;
                  setRange(rng);
                  setKlines(null);
                  setKPage(1);
                  loadKlines(selected, 1, kSize, rng);
                  loadChart(selected, rng);
                }}
              />
              <span className="kb-range-hint">
                已存 {fmt(selected.start_ms, minute)} ~ {fmt(selected.end_ms, minute)}
              </span>
            </Space>
          </div>

          <div className="chart-panel">
            {chartBars.length > 0 ? (
              <EChartsKline bars={chartBars} isMinute={minute} />
            ) : (
              <Empty description="该区间无数据" style={{ margin: "60px 0" }} />
            )}
          </div>

          <div className="detail-table">
            <Table
              rowKey={(r) => String(r[0])}
              size="small"
              loading={kLoading}
              dataSource={klines?.rows ?? []}
              columns={kCols}
              scroll={{ x: 560 }}
              pagination={{
                current: kPage,
                pageSize: kSize,
                total: klines?.total ?? 0,
                showSizeChanger: true,
                pageSizeOptions: [20, 50, 100, 200],
                showTotal: (t) => `共 ${t} 根`,
                onChange: (p, ps) => { if (selected) loadKlines(selected, p, ps, range); },
              }}
            />
          </div>
        </section>
      )}
    </div>
  );
}
