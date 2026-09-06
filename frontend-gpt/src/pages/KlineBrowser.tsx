import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowUpRight,
  CaretLeft,
  CaretRight,
  ChartLineUp,
  List,
  DownloadSimple,
} from "@phosphor-icons/react";
import { api, errorText } from "../api";
import type { Bars, Coverage, Page, Params } from "../types";
import {
  compact,
  dateLabel,
  dateRange,
  loadBars,
  number,
  periodLabel,
} from "../domain";
import {
  Busy,
  Button,
  Empty,
  Notice,
  Pagination,
  Search,
  TableWrap,
} from "../components/Common";
const Chart = lazy(() => import("../components/KlineChart"));

export default function KlineBrowser({ active }: { active: boolean }) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState("1d");
  const [periods, setPeriods] = useState<string[]>([
    "1d",
    "1m",
    "5m",
    "15m",
    "30m",
    "60m",
  ]);
  const [page, setPage] = useState(1);
  const [list, setList] = useState<Page<Coverage>>({
    items: [],
    total: 0,
    page: 1,
    size: 50,
  });
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Coverage | null>(null);
  const [variants, setVariants] = useState<Coverage[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [dates, setDates] = useState({ start: "", end: "" });
  const [range, setRange] = useState({ start: "", end: "" });
  const [dateError, setDateError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [series, setSeries] = useState<Bars | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tablePage, setTablePage] = useState(1);
  const [size, setSize] = useState(20);
  const [table, setTable] = useState<Bars | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState("");
  const wantsRefresh = useRef(true);
  const selection = useRef("");
  useEffect(() => {
    const controller = new AbortController();
    api<{ items: string[] }>("periods", {}, controller.signal)
      .then((d) => setPeriods(d.items))
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const c = new AbortController();
    setListLoading(true);
    setListError("");
    (async () => {
      const first = await api<Page<Coverage>>(
        "coverage",
        { q: search, size: 2000 },
        c.signal,
      );
      const items = [...first.items];
      for (let p = 2; p <= Math.ceil(first.total / 2000); p++)
        items.push(
          ...(
            await api<Page<Coverage>>(
              "coverage",
              { q: search, size: 2000, page: p },
              c.signal,
            )
          ).items,
        );
      if (!c.signal.aborted) setList({ ...first, items });
    })()
      .catch((e) => {
        if (!c.signal.aborted) setListError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setListLoading(false);
      });
    return () => c.abort();
  }, [search, reload]);
  function choose(row: Coverage) {
    setVariants(list.items.filter((r) => r.symbol === row.symbol));
    setDateError("");
    wantsRefresh.current = true;
    selection.current = `${row.symbol}-${row.period}`;
    setSelected(row);
    setDates({ start: "", end: "" });
    setRange({ start: "", end: "" });
    setTablePage(1);
    setSeries(null);
    setTable(null);
    setRefresh((n) => n + 1);
  }
  useEffect(() => {
    if (!selected) return;
    const c = new AbortController();
    setLoading(true);
    setError("");
    setTable(null);
    const shouldRefresh = wantsRefresh.current;
    wantsRefresh.current = false;
    const explicitRange = Boolean(range.start || range.end);
    const params: Params = {
      symbol: selected.symbol,
      period: selected.period,
      ...dateRange(range.start, range.end),
    };
    if (explicitRange) {
      params.start_ms ??= selected.start_ms;
      params.end_ms ??= Date.now();
    }
    (async () => {
      const data = await loadBars(api<Bars>, params, shouldRefresh, c.signal);
      if (!c.signal.aborted) {
        setSeries(data);
        setReload((n) => n + 1);
      }
    })()
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [selected, range, refresh]);
  useEffect(() => {
    if (!selected || !series || loading) return;
    const c = new AbortController();
    setTableLoading(true);
    setTableError("");
    const bounds = dateRange(range.start, range.end);
    if (range.start || range.end) {
      bounds.start_ms ??= selected.start_ms;
      bounds.end_ms ??= Date.now();
    }
    api<Bars>(
      "klines",
      {
        symbol: selected.symbol,
        period: selected.period,
        ...bounds,
        page: tablePage,
        size,
        refresh: series.refreshed ? 1 : undefined,
      },
      c.signal,
    )
      .then((d) =>
        setTable({
          ...d,
          total: series.total,
          rows: d.rows.filter(
            (r) =>
              (bounds.start_ms === undefined ||
                r[0] >= Number(bounds.start_ms)) &&
              (bounds.end_ms === undefined || r[0] <= Number(bounds.end_ms)),
          ),
        }),
      )
      .catch((e) => {
        if (!c.signal.aborted) setTableError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setTableLoading(false);
      });
    return () => c.abort();
  }, [series, loading, selected, tablePage, size, range]);
  function applyDates() {
    try {
      dateRange(dates.start, dates.end);
      setDateError("");
      wantsRefresh.current = Boolean(series?.refreshed);
      setTablePage(1);
      setRange({ ...dates });
    } catch (e) {
      setDateError(errorText(e));
    }
  }
  const grouped = useMemo(() => {
    const groups = new Map<string, Coverage[]>();
    list.items.forEach((r) =>
      groups.set(r.symbol, [...(groups.get(r.symbol) || []), r]),
    );
    return [...groups.values()]
      .filter((rows) => !period || rows.some((r) => r.period === period))
      .map((rows) => ({
        row:
          rows.find((r) => r.period === period) ||
          rows.find((r) => r.period === "1d") ||
          rows[0],
        periods: rows.map((r) => r.period),
      }));
  }, [list.items, period]);
  useEffect(
    () =>
      setPage((p) => Math.min(p, Math.max(1, Math.ceil(grouped.length / 50)))),
    [grouped.length],
  );
  const last = series?.rows.at(-1);
  const change = last && last[1] ? ((last[4] - last[1]) / last[1]) * 100 : 0;
  const coverage =
    list.items.find(
      (r) => r.symbol === selected?.symbol && r.period === selected?.period,
    ) || selected;
  return (
    <div className="market-page">
      <div className="section-top">
        <div>
          <span className="eyebrow">MARKET EXPLORER</span>
          <h2>
            读懂每一次起伏<span className="heading-dot">.</span>
          </h2>
        </div>
        <span className="quiet">
          <span className="small-dot" /> 本地行情库 · 原始价
        </span>
      </div>
      <div className={`market-grid ${collapsed ? "is-collapsed" : ""}`}>
        <aside className="instrument-panel">
          {collapsed ? (
            <button
              className="expand-list"
              onClick={() => setCollapsed(false)}
              aria-label="展开标的列表"
            >
              <List size={20} />
              <span>标的列表</span>
              <CaretRight />
            </button>
          ) : (
            <>
              <div className="panel-head">
                <h3>
                  已存标的 <span>{grouped.length.toLocaleString()}</span>
                </h3>
                {selected && (
                  <button
                    className="icon-button"
                    onClick={() => setCollapsed(true)}
                    aria-label="折叠标的列表"
                  >
                    <CaretLeft />
                  </button>
                )}
              </div>
              <div className="list-filters">
                <Search
                  value={query}
                  setValue={setQuery}
                  onSearch={() => {
                    setSearch(query);
                    setPage(1);
                  }}
                  placeholder="搜索代码 / 名称"
                />
                <select
                  aria-label="行情周期"
                  value={period}
                  onChange={(e) => {
                    setPeriod(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">全部周期</option>
                  {periods.map((p) => (
                    <option key={p} value={p}>
                      {periodLabel(p)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="instrument-labels">
                <span>标的 / 代码</span>
                <span>已存周期 / 数据截止</span>
              </div>
              <div className="instrument-list">
                {listLoading ? (
                  <Busy />
                ) : listError ? (
                  <Notice
                    message={listError}
                    retry={() => setReload((n) => n + 1)}
                  />
                ) : grouped.length ? (
                  grouped
                    .slice((page - 1) * 50, page * 50)
                    .map(({ row, periods: storedPeriods }) => (
                      <button
                        className={`instrument ${selected?.symbol === row.symbol ? "selected" : ""}`}
                        key={`${row.symbol}-${row.period}`}
                        onClick={() => choose(row)}
                      >
                        <span>
                          <strong>{row.name || row.symbol}</strong>
                          <small>{row.symbol}</small>
                        </span>
                        <span>
                          <b title={storedPeriods.map(periodLabel).join(" / ")}>
                            {storedPeriods.map(periodLabel).join(" · ")}
                          </b>
                          <small>{dateLabel(row.end_ms)}</small>
                        </span>
                        <ArrowUpRight size={16} />
                      </button>
                    ))
                ) : (
                  <Empty title="未找到标的">当前筛选下没有已存行情。</Empty>
                )}
              </div>
              <Pagination
                page={page}
                size={50}
                total={grouped.length}
                change={setPage}
                compact
              />
            </>
          )}
        </aside>
        <div className="detail-panel">
          {!selected ? (
            <div className="market-welcome">
              <div className="orbit-graphic">
                <ChartLineUp size={55} weight="thin" />
              </div>
              <span className="eyebrow">YOUR NEXT INSIGHT STARTS HERE</span>
              <h3>
                从一只股票，
                <br />
                看见市场的脉络。
              </h3>
              <p>在左侧选择已存标的，查看 K 线、均线与成交明细。</p>
              <span className="welcome-foot">
                <CaretLeft size={15} /> 选择标的后自动补充最新行情
              </span>
            </div>
          ) : (
            <>
              <div className="quote-head">
                <div>
                  <div className="quote-name">
                    <h3>{selected.name || selected.symbol}</h3>
                    <span>{selected.symbol}</span>
                    <select
                      aria-label="详情周期"
                      className="period-tag"
                      value={selected.period}
                      onChange={(e) => {
                        const next = variants.find(
                          (v) => v.period === e.target.value,
                        );
                        if (next) {
                          wantsRefresh.current = true;
                          setSelected(next);
                          setSeries(null);
                          setTablePage(1);
                        }
                      }}
                    >
                      {variants.map((v) => (
                        <option key={v.period} value={v.period}>
                          {periodLabel(v.period)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="quote-price">
                    <strong
                      className={last ? (change >= 0 ? "up" : "down") : ""}
                    >
                      {number(last?.[4])}
                    </strong>
                    {last && (
                      <span className={change >= 0 ? "up" : "down"}>
                        {change >= 0 ? "+" : ""}
                        {number(change)}% <small>较开盘</small>
                      </span>
                    )}
                  </div>
                </div>
                <div className="quote-meta">
                  <span>最新一根</span>
                  <strong>
                    {dateLabel(last?.[0], selected.period.endsWith("m"))}
                  </strong>
                </div>
              </div>
              <div className="quote-stats">
                {[
                  ["开盘", number(last?.[1])],
                  ["最高", number(last?.[2])],
                  ["最低", number(last?.[3])],
                  ["成交量", compact(last?.[5])],
                  ["成交额", compact(last?.[6])],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <div className="chart-tools">
                <div className="date-range">
                  <input
                    aria-label="开始日期"
                    type="date"
                    value={dates.start}
                    onChange={(e) =>
                      setDates((v) => ({ ...v, start: e.target.value }))
                    }
                  />
                  <span>—</span>
                  <input
                    aria-label="结束日期"
                    type="date"
                    value={dates.end}
                    onChange={(e) =>
                      setDates((v) => ({ ...v, end: e.target.value }))
                    }
                  />
                  <button onClick={applyDates}>查询</button>
                  {(dates.start || dates.end || range.start || range.end) && (
                    <button
                      onClick={() => {
                        wantsRefresh.current = Boolean(series?.refreshed);
                        setDates({ start: "", end: "" });
                        setRange({ start: "", end: "" });
                        setDateError("");
                        setTablePage(1);
                      }}
                    >
                      清空
                    </button>
                  )}
                </div>
                <Button
                  disabled={loading}
                  onClick={() => {
                    wantsRefresh.current = true;
                    setRefresh((n) => n + 1);
                  }}
                >
                  <ArrowClockwise size={16} className={loading ? "spin" : ""} />
                  取最新
                </Button>
              </div>
              {dateError && <Notice message={dateError} />}
              {error && (
                <Notice
                  message={error}
                  retry={() => setRefresh((n) => n + 1)}
                />
              )}
              {series?.refresh_error && (
                <Notice
                  warning
                  message={`行情提示：${series.refresh_error}。${series.rows.length ? "正在显示可用缓存。" : "当前没有可显示的数据。"}`}
                />
              )}
              {loading ? (
                <div className="chart-loading">
                  <Busy />
                </div>
              ) : series?.rows.length ? (
                <Suspense fallback={<Busy />}>
                  <Chart
                    rows={series.rows}
                    period={selected.period}
                    active={active}
                  />
                </Suspense>
              ) : (
                <Empty title="当前区间暂无 K 线" />
              )}
              <div className="coverage-note">
                <span>
                  <DownloadSimple size={13} /> 已存{" "}
                  {dateLabel(coverage?.start_ms)} ~{" "}
                  {dateLabel(coverage?.end_ms)}
                </span>
                <span>
                  显示 {series?.rows.length.toLocaleString() || 0} 根 · 滚轮缩放
                </span>
              </div>
            </>
          )}
        </div>
      </div>
      {selected && (
        <div className="data-block">
          <div className="block-title">
            <h3>
              行情明细 <span>OHLCV</span>
            </h3>
            <span className="quiet">
              {selected.symbol} · {periodLabel(selected.period)}
            </span>
          </div>
          {tableError && <Notice message={tableError} />}
          {table?.refresh_error && (
            <Notice
              warning
              message={`明细回源提示：${table.refresh_error}。正在显示缓存明细。`}
            />
          )}
          {tableLoading ? (
            <Busy />
          ) : table?.rows.length ? (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    {[
                      "时间",
                      "开盘",
                      "最高",
                      "最低",
                      "收盘",
                      "成交量",
                      "成交额",
                    ].map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((r) => (
                    <tr key={r[0]}>
                      <td>{dateLabel(r[0], selected.period.endsWith("m"))}</td>
                      <td>{number(r[1])}</td>
                      <td>{number(r[2])}</td>
                      <td>{number(r[3])}</td>
                      <td className={r[4] >= r[1] ? "up" : "down"}>
                        {number(r[4])}
                      </td>
                      <td>{compact(r[5])}</td>
                      <td>{compact(r[6])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          ) : (
            !loading && <Empty title="暂无明细" />
          )}
          <Pagination
            page={tablePage}
            size={size}
            total={table?.total || 0}
            change={setTablePage}
            resize={(n) => {
              setSize(n);
              setTablePage(1);
            }}
          />
        </div>
      )}
    </div>
  );
}
