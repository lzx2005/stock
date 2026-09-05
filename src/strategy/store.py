"""策略库存储：目录式 JSON，镜像 src/factors/store.py 的原子写风格。

布局（data/strategies/）：
    manifest.json                # {"next_id": N} —— 只存 id 分配器（删除不重用）
    <id>/strategy.json           # 策略元数据（名称/方案/版本指针）
    <id>/versions/<N>/           # 版本目录（版本号从 1 递增）
        version.json             # 版本元数据 + 回测决定参数 + 结果摘要
        results.json             # 复制 skill 产物（完整指标/交易/操作指引）
        equity.csv               # timestamp,equity[,benchmark]
        report.md                # 可读版（v>=2 末尾追加"版本对比"节）
        strategy_v<N>.py         # 策略源码快照（strategy_*.py 改名复制）
        backtest_meta.json       # 边车：复权口径/成本模型/策略参数/区间
        comparison.json          # v>=2 才有（vs v1 + vs 上一版）
        （回测报告.pdf / equity_curve.png 由 build_report 在版本目录生成）

record（import_version）从 skill 的 reports/ scratch 目录复制选定产物进版本
目录；版本目录本身是版本历史的事实来源（reports/ 已 gitignore，不能只存那）。
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from strategy.compare import build_comparison, excess_return, verdict_label
from strategy.errors import StrategyError, StrategyNotFoundError, VersionNotFoundError

# record 时从 scratch 目录复制的产物
_COPY_ARTIFACTS = ("results.json", "equity.csv", "report.md", "backtest_meta.json")

# report.md / PDF 对比表格式化用
_PCT_METRICS = {"total_return", "excess_return", "annual_return", "max_drawdown", "win_rate"}
_MONEY_METRICS = {"final_equity"}


def _fmt_metric(name: str, x):
    """指标值格式化：收益率百分比 / 金额 / 次数 / 小数。None → —。"""
    if x is None:
        return "—"
    try:
        f = float(x)
    except (TypeError, ValueError):
        return "—"
    if name in _PCT_METRICS:
        return f"{f:+.2%}"
    if name in _MONEY_METRICS:
        return f"{f:,.0f}"
    if name == "trade_count":
        return f"{int(f)}"
    return f"{f:.2f}"


class StrategyStore:
    def __init__(self, root: str | os.PathLike = "data/strategies"):
        self.root = Path(root)

    # ---------------- 内部：路径 / 读写 ----------------
    def _manifest_path(self): return self.root / "manifest.json"
    def _strategy_dir(self, sid): return self.root / str(sid)
    def _strategy_json(self, sid): return self._strategy_dir(sid) / "strategy.json"
    def _versions_dir(self, sid): return self._strategy_dir(sid) / "versions"
    def _version_dir(self, sid, v): return self._versions_dir(sid) / str(v)
    def _version_json(self, sid, v): return self._version_dir(sid, v) / "version.json"
    def _comparison_json(self, sid, v): return self._version_dir(sid, v) / "comparison.json"

    def _load_json(self, path: Path, default=None):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            return default

    def _atomic_write(self, path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, path)          # 原子写
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def _next_id(self) -> int:
        manifest = self._load_json(self._manifest_path(), {"next_id": 1}) or {"next_id": 1}
        nid = int(manifest.get("next_id", 1))
        manifest["next_id"] = nid + 1
        self._atomic_write(self._manifest_path(), manifest)
        return nid

    def _read_strategy(self, sid) -> dict:
        info = self._load_json(self._strategy_json(sid))
        if not info:
            raise StrategyNotFoundError(f"策略 {sid} 不存在")
        return info

    @staticmethod
    def _version_summary(v: dict | None, comparison: dict | None) -> dict | None:
        if not v:
            return None
        m = (v.get("results") or {}).get("metrics") or {}
        verdict = None
        if comparison and comparison.get("comparable"):
            verdict = (comparison.get("vs_prev") or {}).get("verdict") \
                or (comparison.get("vs_v1") or {}).get("verdict")
        return {
            "version": v.get("version"),
            "created_at_ms": v.get("created_at_ms"),
            "strategy_class": v.get("strategy_class"),
            "change_note": v.get("change_note"),
            "metrics": {
                "total_return": m.get("total_return"),
                "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "trade_count": m.get("trade_count"),
            },
            "verdict": verdict,
        }

    # ---------------- 策略级 ----------------
    def create_strategy(self, name: str, description: str = "") -> int:
        if not name or not str(name).strip():
            raise StrategyError("策略名不能为空")
        sid = self._next_id()
        now = int(time.time() * 1000)
        self._atomic_write(self._strategy_json(sid), {
            "id": sid,
            "name": str(name),
            "description": str(description),
            "created_at_ms": now,
            "updated_at_ms": now,
            "latest_version": 0,
        })
        return sid

    def list_strategies(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = []
        for p in sorted(self.root.iterdir(),
                        key=lambda p: int(p.name) if p.name.isdigit() else 0):
            if not p.is_dir() or not p.name.isdigit():
                continue
            sid = int(p.name)
            info = self._load_json(p / "strategy.json")
            if not info:
                continue
            latest = int(info.get("latest_version", 0))
            summary = None
            if latest >= 1:
                summary = self._version_summary(
                    self._load_json(self._version_json(sid, latest)),
                    self._load_json(self._comparison_json(sid, latest)))
            out.append({
                "id": sid,
                "name": info.get("name", ""),
                "description": info.get("description", ""),
                "created_at_ms": info.get("created_at_ms"),
                "latest_version": latest,
                "latest": summary,
            })
        return out

    def get_strategy(self, sid) -> dict:
        return self._read_strategy(sid)

    def rename_strategy(self, sid, name: str) -> None:
        if not name or not str(name).strip():
            raise StrategyError("策略名不能为空")
        info = self._read_strategy(sid)
        info["name"] = str(name)
        info["updated_at_ms"] = int(time.time() * 1000)
        self._atomic_write(self._strategy_json(sid), info)

    def delete_strategy(self, sid) -> None:
        if not self._strategy_json(sid).exists():
            raise StrategyNotFoundError(f"策略 {sid} 不存在")
        shutil.rmtree(self._strategy_dir(sid))   # manifest 不动，id 永不重用

    # ---------------- 版本级 ----------------
    def import_version(self, sid, report_dir, *, change_note: str = "") -> int:
        """把一次已完成回测登记为新版本（核心入口）。

        读 report_dir 的 results.json + backtest_meta.json → 建 versions/<N>/、
        复制产物、写 version.json；N>=2 时自动对比 v1 与上一版（写 comparison.json、
        追加 report.md）。返回新版本号。
        """
        info = self._read_strategy(sid)
        src = Path(report_dir)
        results = self._load_json(src / "results.json")
        if not results:
            raise StrategyError(f"{src} 缺 results.json，无法登记回测")
        meta = self._load_json(src / "backtest_meta.json", {}) or {}

        new_ver = int(info.get("latest_version", 0)) + 1
        vdir = self._version_dir(sid, new_ver)
        vdir.mkdir(parents=True, exist_ok=True)

        # 复制产物（strategy_*.py 第一个匹配改名 strategy_v<N>.py；run_*.py 按原名）
        for name in _COPY_ARTIFACTS:
            p = src / name
            if p.is_file():
                shutil.copy2(p, vdir / name)
        for p in sorted(src.glob("strategy_*.py")):
            if p.is_file():
                shutil.copy2(p, vdir / f"strategy_v{new_ver}.py")
                break
        for p in sorted(src.glob("run_*.py")):
            if p.is_file():
                shutil.copy2(p, vdir / p.name)

        strategy_class = meta.get("strategy_class", "")
        params = meta.get("params", {}) or {}
        note = change_note or meta.get("change_note", "")
        metrics = results.get("metrics") or {}
        bench = results.get("benchmark") or {}
        version_doc = {
            "version": new_ver,
            "strategy_id": sid,
            "strategy_name": info.get("name", ""),
            "created_at_ms": int(time.time() * 1000),
            "strategy_file": f"strategy_v{new_ver}.py",
            "strategy_class": strategy_class,
            "params": params,
            "change_note": note,
            "backtest": {
                "symbols": results.get("symbols", []),
                "period": results.get("period", ""),
                "start_ms": meta.get("start_ms"),
                "end_ms": meta.get("end_ms"),
                "start": results.get("start", ""),
                "end": results.get("end", ""),
                "initial_cash": results.get("initial_cash"),
                "adjust": meta.get("adjust"),
                "broker": meta.get("broker", {}) or {},
            },
            "results": {"metrics": metrics, "benchmark": bench},
        }
        version_doc["results"]["excess_return"] = excess_return(version_doc)
        self._atomic_write(self._version_json(sid, new_ver), version_doc)

        comparison = None
        if new_ver >= 2:
            comparison = self.recompute_comparison(sid, new_ver)

        info["latest_version"] = new_ver
        info["updated_at_ms"] = version_doc["created_at_ms"]
        self._atomic_write(self._strategy_json(sid), info)
        return new_ver

    def recompute_comparison(self, sid, v) -> dict | None:
        """重建 v 的 comparison.json 并追加 report.md（幂等）。v1 返回 None。"""
        if v <= 1:
            return None
        self.get_version(sid, v)          # 校验 v 存在
        cur = self.get_version(sid, v)
        v1 = self.get_version(sid, 1)
        prev = self.get_version(sid, v - 1)
        comparison = build_comparison(cur, v1, prev)
        self._atomic_write(self._comparison_json(sid, v), comparison)
        self._append_compare_md(self._version_dir(sid, v), comparison)
        return comparison

    def list_versions(self, sid) -> list[dict]:
        self._read_strategy(sid)
        vdir = self._versions_dir(sid)
        if not vdir.exists():
            return []
        out = []
        for p in sorted(vdir.iterdir(),
                        key=lambda p: int(p.name) if p.name.isdigit() else 0):
            if not p.is_dir() or not p.name.isdigit():
                continue
            s = self._version_summary(self._load_json(p / "version.json"),
                                      self._load_json(p / "comparison.json"))
            if s:
                out.append(s)
        return out

    def get_version(self, sid, v) -> dict:
        self._read_strategy(sid)
        d = self._load_json(self._version_json(sid, v))
        if not d:
            raise VersionNotFoundError(f"策略 {sid} 版本 {v} 不存在")
        return d

    def get_comparison(self, sid, v) -> dict | None:
        if v <= 1:
            return None
        self.get_version(sid, v)
        return self._load_json(self._comparison_json(sid, v))

    # ---------------- 内部：report.md 追加对比节 ----------------
    @staticmethod
    def _append_compare_md(vdir: Path, comparison: dict | None) -> None:
        md_path = vdir / "report.md"
        marker = "## 版本对比"
        existing = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        if marker in existing:
            return                                   # 幂等：已有对比节
        lines = [marker, ""]
        if not comparison or not comparison.get("comparable"):
            note = comparison.get("note", "") if comparison else ""
            lines.append(f"本版与基线回测设置不一致，无法对比：{note}")
        else:
            for key, label in (("vs_v1", "vs v1（原始版）"), ("vs_prev", "vs 上一版")):
                c = comparison.get(key)
                if not c:
                    continue
                lines.append(f"### {label}（版本 {c.get('version')}）")
                if not c.get("comparable"):
                    lines.append(f"不可比：{c.get('note', '')}")
                    lines.append("")
                    continue
                lines.append(f"**结论：{verdict_label(c.get('verdict'))}**")
                lines.append("")
                lines.append("| 指标 | 基准版值 | 本版值 | 差值 | 方向 |")
                lines.append("|---|---|---|---|---|")
                for name, d in c.get("metrics_delta", {}).items():
                    arrow = {True: "↑", False: "↓", None: "—"}.get(d.get("better"), "—")
                    lines.append(f"| {name} | {_fmt_metric(name, d.get('old'))} | "
                                 f"{_fmt_metric(name, d.get('new'))} | "
                                 f"{_fmt_metric(name, d.get('delta'))} | {arrow} |")
                lines.append("")
        text = existing + ("\n" if existing and not existing.endswith("\n") else "") \
            + "\n".join(lines) + "\n"
        md_path.write_text(text, encoding="utf-8")
