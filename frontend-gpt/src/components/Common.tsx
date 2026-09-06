import {
  ArrowLeft,
  ArrowRight,
  ArrowClockwise,
  MagnifyingGlass,
  WarningCircle,
  CircleNotch,
  Database,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
export function Button({
  children,
  tone = "",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: string }) {
  return (
    <button className={`button ${tone} ${className}`} {...props}>
      {children}
    </button>
  );
}
export function Empty({
  title = "这里还没有数据",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Database size={30} weight="duotone" />
      <h3>{title}</h3>
      <p>{children || "试试调整筛选条件，或选择其他数据。"}</p>
    </div>
  );
}
export function Busy() {
  return (
    <div className="busy" role="status">
      <CircleNotch size={20} className="spin" /> 正在读取数据
    </div>
  );
}
export function Notice({
  message,
  retry,
  warning = false,
}: {
  message: string;
  retry?: () => void;
  warning?: boolean;
}) {
  return (
    <div
      className={`notice ${warning ? "warning" : ""}`}
      role={warning ? "status" : "alert"}
    >
      <WarningCircle size={19} />
      <span>{message}</span>
      {retry && (
        <button onClick={retry}>
          <ArrowClockwise size={16} /> 重试
        </button>
      )}
    </div>
  );
}
export function Search({
  value,
  setValue,
  onSearch,
  placeholder,
}: {
  value: string;
  setValue: (v: string) => void;
  onSearch: () => void;
  placeholder: string;
}) {
  return (
    <form
      className="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch();
      }}
    >
      <MagnifyingGlass size={18} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button aria-label="搜索" type="submit">
        <ArrowRight size={16} />
      </button>
    </form>
  );
}
export function Pagination({
  page,
  size,
  total,
  change,
  resize,
  compact = false,
}: {
  page: number;
  size: number;
  total: number;
  change: (p: number) => void;
  resize?: (n: number) => void;
  compact?: boolean;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className={`pagination ${compact ? "compact" : ""}`}>
      <span>共 {total.toLocaleString()} 条</span>
      <div>
        {resize && (
          <select
            aria-label="每页条数"
            value={size}
            onChange={(e) => resize(+e.target.value)}
          >
            {[20, 50, 100, 200].map((n) => (
              <option value={n} key={n}>
                {n} 条 / 页
              </option>
            ))}
          </select>
        )}
        <button
          aria-label="上一页"
          disabled={page <= 1}
          onClick={() => change(page - 1)}
        >
          <ArrowLeft size={15} />
        </button>
        <span>
          {page} / {pages}
        </span>
        <button
          aria-label="下一页"
          disabled={page >= pages}
          onClick={() => change(page + 1)}
        >
          <ArrowRight size={15} />
        </button>
      </div>
    </div>
  );
}
export function Switch({
  on,
  change,
  label,
  disabled = false,
}: {
  on: boolean;
  change: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={`switch ${on ? "on" : ""}`}
      onClick={change}
    >
      <span />
    </button>
  );
}
export function Lamp({ on }: { on: boolean }) {
  return (
    <span className="lamp-wrap">
      <i className={`lamp ${on ? "lit" : ""}`} />
      {on ? "亮" : "灭"}
    </span>
  );
}
export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}
