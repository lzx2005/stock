import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from datacenter.constants import period_dir_token
from factors.compute import apply_factor
from factors.registry import get_factor


class FactorStore:
    def __init__(self, dc, root="data/factors", adjust="forward"):
        self.dc = dc
        self.root = Path(root)
        self.adjust = adjust

    # ---- 内部：路径 / 读写 ----
    def _fp_dir(self, fingerprint): return self.root / fingerprint
    def _path(self, fingerprint, symbol, period):
        return self._fp_dir(fingerprint) / f"symbol={symbol}" / f"period={period_dir_token(period)}" / "part.parquet"

    def _load(self, path) -> pd.Series:
        if not path.exists():
            return pd.Series(dtype=float)
        df = pd.read_parquet(path)
        if df.empty:
            return pd.Series(dtype=float)
        return pd.Series(df["value"].values, index=df["timestamp"].values)

    def _save(self, fingerprint, symbol, period, series: pd.Series, defn=None, merged=None):
        if series.empty:
            return  # 空不落盘
        path = self._path(fingerprint, symbol, period)
        path.parent.mkdir(parents=True, exist_ok=True)
        if defn is not None:
            meta = self._fp_dir(fingerprint) / "factor.json"
            if not meta.exists():      # 定义快照，首次写入
                meta.write_text(json.dumps({"name": defn.name, "params": merged,
                    "version": defn.version, "adjust": self.adjust,
                    "category": defn.category, "period": defn.period, "doc": defn.doc},
                    ensure_ascii=False, indent=2))
        out = pd.DataFrame({"timestamp": series.index, "value": series.values})
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".parquet.tmp")
        try:
            os.close(fd)
            out.to_parquet(tmp, index=False)
            os.replace(tmp, path)          # 原子写
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # ---- 取数 ----
    def _fetch_compute(self, symbol, period, start_ms, end_ms, defn, params):
        df = self.dc.get_klines(symbol, period, start_ms, end_ms, adjust=self.adjust)
        if df is None or df.empty:
            return pd.Series(dtype=float, name=defn.name)
        df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        vals = apply_factor(defn, df, params)
        return pd.Series(vals.values, index=df["timestamp"].values, name=defn.name)

    def _lookback(self, defn, merged) -> int:
        lb = defn.lookback
        return lb(merged) if callable(lb) else int(lb or 0)

    def get(self, symbol, name, params=None, period="1d", start_ms=None, end_ms=None):
        if start_ms is None or end_ms is None:
            raise ValueError("start_ms/end_ms 必填")
        defn, merged, fp = get_factor(name, params, adjust=self.adjust)
        path = self._path(fp, symbol, period)
        stored = self._load(path)
        if not stored.empty and stored.index.min() <= start_ms and stored.index.max() >= end_ms:
            return stored.loc[start_ms:end_ms].rename(defn.name)  # 全覆盖，直接切片
        lo, hi = (int(stored.index.min()), int(stored.index.max())) if not stored.empty else (None, None)
        parts = []
        if lo is None:
            parts.append(self._fetch_compute(symbol, period, start_ms, end_ms, defn, merged))
        else:
            if start_ms < lo: parts.append(self._fetch_compute(symbol, period, start_ms, lo - 1, defn, merged))
            if end_ms > hi:
                lb = self._lookback(defn, merged)
                fetch_from = max(start_ms, hi + 1 - lb)
                tail = self._fetch_compute(symbol, period, fetch_from, end_ms, defn, merged)
                parts.append(tail.loc[hi + 1:end_ms])   # 丢弃 seed 区，只留缺口区
        new = pd.concat(parts) if parts else pd.Series(dtype=float)
        combined = stored.combine_first(new).sort_index()   # 重叠区以已存为准
        self._save(fp, symbol, period, combined, defn, merged)
        return combined.loc[start_ms:end_ms].rename(defn.name)

    def refresh(self, symbol, name, params=None, period="1d", start_ms=None, end_ms=None):
        if start_ms is None or end_ms is None:
            raise ValueError("start_ms/end_ms 必填")
        defn, merged, fp = get_factor(name, params, adjust=self.adjust)
        new = self._fetch_compute(symbol, period, start_ms, end_ms, defn, merged)
        self._save(fp, symbol, period, new, defn, merged)   # 覆盖写，忽略缓存
        return new.loc[start_ms:end_ms].rename(defn.name)

    def drop(self, name, params=None, period=None, adjust=None):
        import shutil
        defn, merged, fp = get_factor(name, params, adjust=adjust or self.adjust)
        d = self._fp_dir(fp)
        if period is None:
            shutil.rmtree(d, ignore_errors=True)
            return
        for sym_dir in d.glob("symbol=*"):   # 只删该 period 子目录
            shutil.rmtree(sym_dir / f"period={period_dir_token(period)}", ignore_errors=True)

    def warm(self, symbols, factors, period="1d", start_ms=None, end_ms=None, show_progress=False):
        total = len(symbols) * len(factors)
        done = 0
        for s in symbols:
            for f in factors:
                self.get(s, f, None, period, start_ms, end_ms)
                done += 1
                if show_progress: print(f"\r[{done}/{total}] {s} {f}", end="", flush=True)
        if show_progress: print()

    def list_stored(self) -> list[dict]:
        """枚举已存因子数据：扫 root/*/factor.json。每指纹含实际存在的
        symbol×period 组合（cells）与行数合计。纯读，不触发计算/回源。

        行数用 pyarrow parquet metadata（不读数据块），因子数据量小，全量统计。
        """
        if not self.root.exists():
            return []
        out = []
        for fp_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            meta = fp_dir / "factor.json"
            if not meta.exists():
                continue
            try:
                info = json.loads(meta.read_text())
            except (OSError, ValueError):
                continue
            cells = []
            for sym_dir in sorted(fp_dir.glob("symbol=*")):
                symbol = sym_dir.name[len("symbol="):]
                for period_dir in sorted(sym_dir.glob("period=*")):
                    period = period_dir.name[len("period="):]
                    part = period_dir / "part.parquet"
                    if not part.exists():
                        continue
                    try:
                        rows = pq.read_metadata(part).num_rows
                    except Exception:
                        rows = 0
                    cells.append({"symbol": symbol, "period": period, "rows": rows})
            out.append({
                "fingerprint": fp_dir.name,
                "name": info.get("name", ""),
                "params": info.get("params", {}),
                "version": info.get("version", 1),
                "adjust": info.get("adjust", self.adjust),
                "period": info.get("period", "1d"),
                "category": info.get("category", ""),
                "doc": info.get("doc", ""),
                "cells": cells,
                "total_rows": sum(c["rows"] for c in cells),
            })
        return out

    def load_stored(self, fingerprint: str, symbol: str, period: str) -> pd.Series:
        """纯读已存因子值（索引=timestamp ms，值=value）。文件缺失返回空 Series。"""
        return self._load(self._path(fingerprint, symbol, period))
