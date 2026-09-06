import type { Bars, Params, TaskInput } from "./types";
export function movingAverage(values: number[], n: number): (number | null)[] {
  let sum = 0;
  return values.map((v, i) => {
    sum += v;
    if (i >= n) sum -= values[i - n];
    return i < n - 1 ? null : +(sum / n).toFixed(4);
  });
}
export function dateRange(start: string, end: string): Params {
  const start_ms = start ? Date.parse(`${start}T00:00:00+08:00`) : undefined;
  const end_ms = end ? Date.parse(`${end}T23:59:59.999+08:00`) : undefined;
  if (
    (start_ms !== undefined && !Number.isFinite(start_ms)) ||
    (end_ms !== undefined && !Number.isFinite(end_ms))
  )
    throw new Error("请选择有效日期");
  if (start_ms !== undefined && end_ms !== undefined && start_ms > end_ms)
    throw new Error("开始日期不能晚于结束日期");
  return { start_ms, end_ms };
}
export function validateTask(
  task: Pick<TaskInput, "name" | "symbol" | "script" | "interval_sec">,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!task.name.trim()) errors.name = "请输入任务名称";
  if (!task.symbol.trim()) errors.symbol = "请输入标的代码";
  if (!task.script.trim()) errors.script = "请输入盯盘脚本";
  if (!Number.isInteger(task.interval_sec) || task.interval_sec < 60)
    errors.interval_sec = "轮询间隔须为不小于 60 的整数";
  return errors;
}
export async function loadBars(
  request: (path: string, params: Params, signal: AbortSignal) => Promise<Bars>,
  params: Params,
  refresh: boolean,
  signal: AbortSignal,
): Promise<Bars> {
  const first = await request(
    "klines",
    { ...params, page: 1, size: 2000, refresh: refresh ? 1 : undefined },
    signal,
  );
  const rows = [...first.rows];
  let warning = first.refresh_error;
  for (let page = 2; page <= Math.ceil(first.total / 2000); page++) {
    const next = await request(
      "klines",
      { ...params, page, size: 2000, refresh: first.refreshed ? 1 : undefined },
      signal,
    );
    if (next.refresh_error) warning = next.refresh_error;
    rows.push(...next.rows);
  }
  const unique = [...new Map(rows.map((row) => [row[0], row])).values()].sort(
    (a, b) => a[0] - b[0],
  );
  const filtered = unique.filter(
    (row) =>
      (params.start_ms === undefined || row[0] >= Number(params.start_ms)) &&
      (params.end_ms === undefined || row[0] <= Number(params.end_ms)),
  );
  return {
    ...first,
    rows: filtered,
    total: filtered.length,
    refresh_error: warning,
  };
}
export function dateLabel(ts: number | null | undefined, minute = false) {
  if (!ts) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    ...(minute
      ? ({ hour: "2-digit", minute: "2-digit", hour12: false } as const)
      : {}),
  })
    .format(ts)
    .replaceAll("/", "-");
}
export const number = (v: number | null | undefined, decimals = 2) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : v.toLocaleString("zh-CN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
export function compact(v: number | null | undefined) {
  return v == null
    ? "—"
    : Math.abs(v) >= 1e8
      ? `${number(v / 1e8)} 亿`
      : Math.abs(v) >= 1e4
        ? `${number(v / 1e4)} 万`
        : number(v, 0);
}
export function relative(ts: number | null) {
  if (!ts) return "尚未运行";
  const sec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  return sec < 60
    ? `${sec} 秒前`
    : sec < 3600
      ? `${Math.floor(sec / 60)} 分钟前`
      : sec < 86400
        ? `${Math.floor(sec / 3600)} 小时前`
        : `${Math.floor(sec / 86400)} 天前`;
}
export const periodLabel = (p: string) =>
  ({ "1d": "日线", "1w": "周线", "1M": "月线", "1Q": "季线", "1Y": "年线" })[
    p
  ] || `${p.replace("m", "")} 分钟`;
