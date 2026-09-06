import { useEffect, useState } from "react";
import {
  ArrowRight,
  CaretRight,
  Flask,
  Folders,
  Stack,
} from "@phosphor-icons/react";
import { api, errorText } from "../api";
import type { Cell, Factor, FactorDir, Page } from "../types";
import { dateLabel, number, periodLabel } from "../domain";
import {
  Busy,
  Empty,
  Notice,
  Pagination,
  Search,
  TableWrap,
} from "../components/Common";
const category = (c: string) =>
  ({ trend: "趋势", momentum: "动量", volatility: "波动", volume: "量能" })[
    c
  ] || c;
export default function FactorBrowser() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [reload, setReload] = useState(0);
  const [factors, setFactors] = useState<Factor[]>([]);
  const [dirs, setDirs] = useState<FactorDir[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [factor, setFactor] = useState<Factor | null>(null);
  const [directory, setDirectory] = useState<FactorDir | null>(null);
  const [cell, setCell] = useState<Cell | null>(null);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(50);
  const [values, setValues] = useState<{
    total: number;
    rows: [number, number | null][];
  }>({ total: 0, rows: [] });
  const [valuesLoading, setValuesLoading] = useState(false);
  const [valuesError, setValuesError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError("");
    async function all<T>(path: string) {
      const first = await api<Page<T>>(path, { size: 2000 }, c.signal);
      const items = [...first.items];
      for (let p = 2; p <= Math.ceil(first.total / 2000); p++)
        items.push(
          ...(await api<Page<T>>(path, { size: 2000, page: p }, c.signal))
            .items,
        );
      return items;
    }
    Promise.all([all<Factor>("factors"), all<FactorDir>("factor-dirs")])
      .then(([f, d]) => {
        setFactors(f);
        setDirs(d);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [reload]);
  useEffect(() => {
    if (!cell || !directory) return;
    const c = new AbortController();
    setValuesLoading(true);
    setValuesError("");
    api<typeof values>(
      "factor-values",
      {
        fingerprint: directory.fingerprint,
        symbol: cell.symbol,
        period: cell.period,
        page,
        size,
      },
      c.signal,
    )
      .then(setValues)
      .catch((e) => {
        if (!c.signal.aborted) setValuesError(errorText(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setValuesLoading(false);
      });
    return () => c.abort();
  }, [cell, directory, page, size, reload]);
  const shown = factors.filter((f) =>
    `${f.name} ${f.doc}`.toLowerCase().includes(search.toLowerCase()),
  );
  const stored = dirs.filter((d) => d.name === factor?.name);
  function reset() {
    setFactor(null);
    setDirectory(null);
    setCell(null);
  }
  return (
    <div className="factor-page">
      <div className="section-top">
        <div>
          <span className="eyebrow">FACTOR LIBRARY</span>
          <h2>
            让直觉，有据可循<span className="heading-dot">.</span>
          </h2>
        </div>
        <Flask size={40} weight="thin" />
      </div>
      <div className="factor-summary">
        <div>
          <Flask size={25} />
          <span>
            已注册因子
            <strong>{factors.length.toString().padStart(2, "0")}</strong>
          </span>
        </div>
        <div>
          <Folders size={25} />
          <span>
            参数目录<strong>{dirs.length.toString().padStart(2, "0")}</strong>
          </span>
        </div>
        <div>
          <Stack size={25} />
          <span>
            已计算数据
            <strong>
              {dirs.reduce((sum, d) => sum + d.total_rows, 0).toLocaleString()}
              <small> 行</small>
            </strong>
          </span>
        </div>
        <p>
          将市场拆解成可验证的条件。
          <br />
          每一个因子，都是研究的起点。
        </p>
      </div>
      <nav className="breadcrumbs" aria-label="因子下钻路径">
        <button onClick={reset}>全部因子</button>
        {factor && (
          <>
            <CaretRight />
            <button
              onClick={() => {
                setDirectory(null);
                setCell(null);
              }}
            >
              {factor.name}
            </button>
          </>
        )}
        {directory && (
          <>
            <CaretRight />
            <button onClick={() => setCell(null)}>
              {JSON.stringify(directory.params)}
            </button>
          </>
        )}
        {cell && (
          <>
            <CaretRight />
            <span>
              {cell.symbol} · {periodLabel(cell.period)}
            </span>
          </>
        )}
      </nav>
      {error ? (
        <Notice message={error} retry={() => setReload((n) => n + 1)} />
      ) : loading ? (
        <Busy />
      ) : (
        <div className="data-block factor-block">
          <div className="block-title">
            <h3>
              {cell
                ? `因子值 · ${factor?.name}`
                : directory
                  ? "标的与周期"
                  : factor
                    ? `已存数据目录 · ${factor.name}`
                    : "探索因子"}{" "}
              <span>
                {cell
                  ? "VALUES"
                  : directory
                    ? "SYMBOLS"
                    : factor
                      ? "PARAMETERS"
                      : "REGISTRY"}
              </span>
            </h3>
            {!factor && (
              <Search
                value={query}
                setValue={setQuery}
                onSearch={() => setSearch(query)}
                placeholder="搜索因子名称 / 说明"
              />
            )}
          </div>
          {!factor &&
            (shown.length ? (
              <TableWrap>
                <table className="clickable-table">
                  <thead>
                    <tr>
                      <th>因子名称</th>
                      <th>默认参数</th>
                      <th>版本</th>
                      <th>类别</th>
                      <th>说明 / 条件</th>
                      <th>已存目录</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((f) => (
                      <tr
                        key={f.name}
                        tabIndex={0}
                        onKeyDown={(e) => e.key === "Enter" && setFactor(f)}
                        onClick={() => setFactor(f)}
                      >
                        <td>
                          <strong className="factor-name">{f.name}</strong>
                        </td>
                        <td>
                          <code>{JSON.stringify(f.default_params)}</code>
                        </td>
                        <td>v{f.version}</td>
                        <td>
                          <span className="category">
                            {category(f.category)}
                          </span>
                        </td>
                        <td className="description-cell" title={f.doc}>
                          {f.doc}
                        </td>
                        <td>{f.stored_dir_count}</td>
                        <td>
                          <ArrowRight size={17} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            ) : (
              <Empty title="没有匹配的因子" />
            ))}
          {factor &&
            !directory &&
            (stored.length ? (
              <TableWrap>
                <table className="clickable-table">
                  <thead>
                    <tr>
                      {[
                        "参数指纹",
                        "参数",
                        "版本",
                        "复权方式",
                        "组合数",
                        "总行数",
                        "",
                      ].map((h, i) => (
                        <th key={i}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {stored.map((d) => (
                      <tr
                        key={d.fingerprint}
                        tabIndex={0}
                        onKeyDown={(e) => e.key === "Enter" && setDirectory(d)}
                        onClick={() => setDirectory(d)}
                      >
                        <td>
                          <code>{d.fingerprint}</code>
                        </td>
                        <td>
                          <code>{JSON.stringify(d.params)}</code>
                        </td>
                        <td>v{d.version}</td>
                        <td>
                          {{
                            forward: "前复权",
                            backward: "后复权",
                            none: "不复权",
                          }[d.adjust] || d.adjust}
                        </td>
                        <td>{d.cells.length}</td>
                        <td>{d.total_rows.toLocaleString()}</td>
                        <td>
                          <ArrowRight />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            ) : (
              <Empty title="这个因子还没有已存数据">
                运行使用该因子的回测或因子预热后，可在此查看计算结果。
              </Empty>
            ))}
          {directory &&
            !cell &&
            (directory.cells.length ? (
              <TableWrap>
                <table className="clickable-table">
                  <thead>
                    <tr>
                      <th>标的</th>
                      <th>周期</th>
                      <th>行数</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {directory.cells.map((c) => (
                      <tr
                        key={`${c.symbol}-${c.period}`}
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            setCell(c);
                            setPage(1);
                          }
                        }}
                        onClick={() => {
                          setCell(c);
                          setPage(1);
                        }}
                      >
                        <td>
                          <strong>{c.symbol}</strong>
                        </td>
                        <td>{periodLabel(c.period)}</td>
                        <td>{c.rows.toLocaleString()}</td>
                        <td>
                          <ArrowRight />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            ) : (
              <Empty />
            ))}
          {cell && (
            <>
              <p className="value-context">
                {factor?.name} {JSON.stringify(directory?.params)} ·{" "}
                {cell.symbol} · {periodLabel(cell.period)}
              </p>
              {valuesLoading ? (
                <Busy />
              ) : valuesError ? (
                <Notice
                  message={valuesError}
                  retry={() => setReload((n) => n + 1)}
                />
              ) : values.rows.length ? (
                <TableWrap>
                  <table>
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>因子值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {values.rows.map(([ts, value]) => (
                        <tr key={ts}>
                          <td>{dateLabel(ts, cell.period.endsWith("m"))}</td>
                          <td>{number(value, 6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              ) : (
                <Empty />
              )}
              <Pagination
                total={values.total}
                page={page}
                size={size}
                change={setPage}
                resize={(n) => {
                  setSize(n);
                  setPage(1);
                }}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}
