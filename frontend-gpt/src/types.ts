export type Params = Record<string, string | number | boolean | undefined>;
export type Bar = [number, number, number, number, number, number, number];
export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}
export interface Coverage {
  symbol: string;
  code: string | null;
  name: string | null;
  period: string;
  start_ms: number;
  end_ms: number;
  updated_at: number;
}
export interface Bars {
  rows: Bar[];
  total: number;
  refreshed?: boolean;
  refresh_error?: string | null;
}
export interface Factor {
  name: string;
  category: string;
  period: string;
  version: number;
  default_params: Record<string, unknown>;
  doc: string;
  stored_dir_count: number;
}
export interface Cell {
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
  cells: Cell[];
  total_rows: number;
}
export interface TaskInput {
  name: string;
  symbol: string;
  script: string;
  interval_sec: number;
  notify: number;
  description: string;
}
export interface Task extends TaskInput {
  id: number;
  enabled: number;
  lamp_on: number;
  poll_count: number;
  signal_count: number;
  error_count: number;
  last_error: string | null;
  last_run_at: number | null;
  created_at: number;
}
export interface Signal {
  id: number;
  task_id: number;
  ts: number;
  kind: string;
  price: number | null;
  message: string;
}
