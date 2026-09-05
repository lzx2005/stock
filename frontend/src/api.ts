// 后端 API 封装（全部只读，服务端分页）
export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}

export interface CoverageRow {
  symbol: string;
  code: string | null;
  name: string | null;
  period: string;
  start_ms: number;
  end_ms: number;
  updated_at: number;
}

export type KlineRow = [number, number, number, number, number, number, number];

export interface KlinesResp {
  symbol: string;
  period: string;
  total: number;
  page: number;
  size: number;
  rows: KlineRow[];
}

export interface FactorRow {
  name: string;
  category: string;
  period: string;
  version: number;
  default_params: Record<string, unknown>;
  doc: string;
  stored_dir_count: number;
}

export interface StoredCell {
  symbol: string;
  period: string;
  rows: number;
}

export interface FactorDir {
  fingerprint: string;
  name: string;
  params: Record<string, unknown>;
  version: number;
  adjust: string;
  period: string;
  category: string;
  doc: string;
  cells: StoredCell[];
  total_rows: number;
}

export interface FactorValuesResp {
  fingerprint: string;
  symbol: string;
  period: string;
  total: number;
  page: number;
  size: number;
  rows: [number, number | null][];
}

async function get<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") qs.set(k, String(v));
  }
  const url = `/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`请求失败(${res.status}): ${detail}`);
  }
  return res.json();
}

export const api = {
  periods: () => get<Page<string>>("/periods", {}),
  coverage: (q: string, period: string, page: number, size: number) =>
    get<Page<CoverageRow>>("/coverage", { q, period, page, size }),
  klines: (symbol: string, period: string, start_ms: number, end_ms: number, page: number, size: number) =>
    get<KlinesResp>("/klines", { symbol, period, start_ms, end_ms, page, size }),
  factors: (q: string, page: number, size: number) =>
    get<Page<FactorRow>>("/factors", { q, page, size }),
  factorDirs: (q: string, page: number, size: number) =>
    get<Page<FactorDir>>("/factor-dirs", { q, page, size }),
  factorValues: (fingerprint: string, symbol: string, period: string, page: number, size: number) =>
    get<FactorValuesResp>("/factor-values", { fingerprint, symbol, period, page, size }),
};
