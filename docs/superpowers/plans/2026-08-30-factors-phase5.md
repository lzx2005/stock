# 第五期：因子库（定义 + 存储 + 复用）

> 2026-08-30 启动。git 延续前几期约定：本期不接 git，所有 Commit 步骤保持未勾，用户说"提交"时统一处理。
> 产品方向（用户确认）：不做选股（同花顺一句话选股承担）；回测只验证哪些条件利于收益；因子 = 可转述为同花顺条件句的原子条件。详见 spec。

**Goal:** 建立因子库 `src/factors/`，统一管理量价因子定义与计算值——算一次、存 parquet、回测惰性取数复用，改造双均线走因子库跑通整条链。

**Architecture:** `registry`（定义+指纹）→ `compute`（apply_factor，复用 backtest.indicators）→ `store`（FactorStore：parquet 分区 + fetch-through 惰性补算，镜像 KlineStore/CacheResolver 模式）。策略在 `init` 一次性取整段因子序列、`on_bar` 按时间戳对齐（滚动指标因果、无前视）。

**Spec:** `docs/superpowers/specs/2026-08-30-factor-library-design.md`

## 全局约束（spec 原文转抄）

- 因子值按 **forward（前复权）** 计算并存储（与回测引擎 `adjust="forward"` 一致）。
- 缓存指纹 = `sha1(name|sorted_params_json|version|adjust)[:16]`；改参数/公式/复权口径自动换 key 重算，旧值保留不误删。
- 因果性约束：一期因子必须"bar i 的值只依赖 ≤i 的数据"（rolling/ewm/shift 类）——这是无前视与整段预取的根基。
- 除权导致前复权历史值漂移、覆盖校验检测不到 → 提供 `refresh()` 手动兜底。
- 补算只算缺口（请求区间 \ 已存覆盖区间），不重算已覆盖区；重叠区以已存为准。
- 内置因子**零重复实现**：指标类引用 `backtest.indicators`，条件因子（vol_ratio/mom/bias）用 pandas 原生滚动算子。
- 测试沿用 `tests/conftest.py` 的 `make_kline_df` 与 `tests/test_engine.py` 的 `FakeDC` 鸭子类型模式，不依赖真实数据源。
- 数据根目录：`FactorStore(dc, root="data/factors")`（构造参数可注入临时目录供测试）。

## 关键接口（跨任务引用，先约定）

```python
# registry.py
@dataclass(frozen=True)
class FactorDefinition:
    name: str; category: str = "price-volume"; period: str = "1d"
    version: int = 1; inputs: tuple[str, ...] = ("close",)
    default_params: dict = field(default_factory=dict); doc: str = ""
    lookback: int | Callable[[dict], int] = 0  # 尾部缺口补算的前向 seed 根数；int 或 (merged_params)->int
    fn: Callable  # (df: DataFrame, **params) -> Series，值按 df.index 对齐

def register_factor(name, *, category="price-volume", period="1d", version=1,
                    inputs=("close",), default_params=None, doc="",
                    lookback: int | Callable[[dict], int] | None = None) -> Callable  # 装饰器（None/0 → 0）
def get_factor(name, params=None, adjust="forward") -> tuple[FactorDefinition, dict, str]
    # 返回 (定义, 合并后的参数, 指纹)。name 未注册抛 FactorUnknownError；
    # 出现未知参数抛 FactorParamError。
def list_factors() -> list[str]

# compute.py
def apply_factor(defn: FactorDefinition, df: pd.DataFrame, params: dict) -> pd.Series
    # 校验 df 含 defn.inputs 列（缺列抛 FactorInputError）→ defn.fn(df, **params)

# store.py
class FactorStore:
    def __init__(self, dc, root: str | os.PathLike = "data/factors", adjust: str = "forward"): ...
    def get(self, symbol, name, params=None, period="1d", start_ms=None, end_ms=None) -> pd.Series
        # start_ms/end_ms 必填；返回 Series 索引=timestamp(ms int)、name=因子名
    def refresh(self, symbol, name, params=None, period="1d", start_ms=None, end_ms=None) -> pd.Series
    def drop(self, name, params=None, period=None, adjust=None) -> None
    def warm(self, symbols, factors, period="1d", start_ms=None, end_ms=None, show_progress=False) -> None
```

## Task 1: 因子定义注册表（registry.py）

**Files:**
- Create: `src/factors/__init__.py`（导出 FactorStore/register_factor/get_factor/list_factors/异常，暂不引 store）
- Create: `src/factors/registry.py`
- Test: `tests/test_factor_registry.py`

**Produces:** `FactorDefinition` / `register_factor` / `get_factor` / `list_factors` / `FactorError` 异常族（Task 2/3 依赖）。

- [x] **Step 1: 写失败测试** `tests/test_factor_registry.py`

```python
import json, hashlib
import pytest
from factors.registry import (FactorDefinition, register_factor, get_factor,
                              list_factors, FactorUnknownError, FactorParamError)

def _fp(name="ma", params=None, version=1, adjust="forward"):
    p = json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{name}|{p}|{version}|{adjust}".encode()).hexdigest()[:16]

def test_register_and_get_factor():
    register_factor("ma", inputs=("close",), default_params={"n": 20},
                    doc="N日简单均线")(lambda df, n=20: df["close"].rolling(n).mean())
    defn, params, fp = get_factor("ma", {"n": 5})
    assert defn.name == "ma" and params == {"n": 5} and fp == _fp("ma", {"n": 5})

def test_get_factor_merges_defaults():
    register_factor("t", default_params={"a": 1, "b": 2})(lambda df, a=1, b=2: df["close"])
    _, params, _ = get_factor("t", {"b": 9})
    assert params == {"a": 1, "b": 9}

def test_get_factor_unknown_name():
    with pytest.raises(FactorUnknownError): get_factor("nope")

def test_get_factor_unknown_param():
    register_factor("u", default_params={"a": 1})(lambda df, a=1: df["close"])
    with pytest.raises(FactorParamError): get_factor("u", {"zzz": 3})

def test_fingerprint_changes_on_each_field():
    assert _fp("ma", {"n": 5}) != _fp("ma", {"n": 6})          # 参数
    assert _fp("ma") != _fp("ema")                             # 名字
    assert _fp("ma", version=2) != _fp("ma", version=1)        # 版本
    assert _fp("ma", adjust="none") != _fp("ma", adjust="forward")  # 复权

def test_list_factors_sorted_unique():
    assert list_factors() == sorted(list_factors())
```

- [x] **Step 2: 运行确认失败** → `pytest tests/test_factor_registry.py -v`，预期 FAIL（模块不存在）
- [x] **Step 3: 实现** `src/factors/registry.py`

```python
import hashlib, json
from dataclasses import dataclass, field
from typing import Callable

@dataclass(frozen=True)
class FactorDefinition:
    name: str
    category: str = "price-volume"
    period: str = "1d"
    version: int = 1
    inputs: tuple[str, ...] = ("close",)
    default_params: dict = field(default_factory=dict)
    doc: str = ""
    lookback: int | Callable[[dict], int] = 0  # 尾部缺口补算的前向 seed 根数；int 或 (merged_params)->int
    fn: Callable  # (df: DataFrame, **params) -> Series，值按 df.index 对齐

class FactorError(Exception): ...
class FactorUnknownError(FactorError): ...
class FactorParamError(FactorError): ...
class FactorInputError(FactorError): ...

REGISTRY: dict[str, FactorDefinition] = {}
__all__ = ["FactorDefinition", "register_factor", "get_factor", "list_factors",
           "FactorError", "FactorUnknownError", "FactorParamError", "FactorInputError"]

def register_factor(name, *, category="price-volume", period="1d", version=1,
                    inputs=("close",), default_params=None, doc="", lookback=None):
    def deco(fn):
        inputs = (inputs,) if isinstance(inputs, str) else tuple(inputs)  # 字符串脚枪防护
        REGISTRY[name] = FactorDefinition(name=name, category=category, period=period,
                                          version=version, inputs=inputs,
                                          default_params=dict(default_params or {}),
                                          doc=doc, lookback=lookback or 0, fn=fn)  # None/0 → 0
        return fn
    return deco

def _fingerprint(name, params, version, adjust) -> str:
    p = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{name}|{p}|{version}|{adjust}".encode()).hexdigest()[:16]

def get_factor(name, params=None, adjust="forward"):
    if name not in REGISTRY:
        raise FactorUnknownError(f"未注册因子 {name}：请先 import factors.factors 注册内置因子（list_factors() 可查）")
    defn = REGISTRY[name]
    merged = dict(defn.default_params)
    unknown = set((params or {})) - set(merged)
    if unknown: raise FactorParamError(f"{name}: 未知参数 {sorted(unknown)}")
    merged.update(params or {})
    return defn, merged, _fingerprint(name, merged, defn.version, adjust)

def list_factors() -> list[str]:
    return sorted(REGISTRY)
```

`src/factors/__init__.py`：`from factors.registry import *`（后续 Task 3 加 FactorStore）。`factors/__init__.py` 不 import `factors.factors`（避免测试污染，由使用方显式 import）。
- [x] **Step 4: 运行确认通过** → `pytest tests/test_factor_registry.py -v`，PASS
- [ ] **Step 5: Commit**（不执行，保持未勾）

## Task 2: 计算层 + 内置因子（compute.py + factors.py）

**Files:**
- Create: `src/factors/compute.py`
- Create: `src/factors/factors.py`（import 即注册全部内置因子）
- Test: `tests/test_factor_compute.py`

**Consumes:** Task 1 的 `register_factor` / `FactorInputError`；`backtest.indicators`。
**Produces:** `apply_factor` + 注册好的因子名（ma/ema/rsi/atr/macd_hist/kdj_j/boll_up/boll_low/vol_ratio/mom/bias）供 Task 3/4 用。

- [x] **Step 1: 写失败测试** `tests/test_factor_compute.py`

```python
import pandas as pd
import pytest
from conftest import make_kline_df
import backtest.indicators as ind
import factors.factors  # noqa: F401  —— import 即注册
from factors.compute import apply_factor
from factors.registry import get_factor, FactorInputError

def _df(n=60):
    df = make_kline_df("600000.SH", start_ms=0, n=n, step_ms=86_400_000)  # 日线
    # 给价格一点变化，让 rolling 值非平凡
    df["close"] = df["close"] + df["close"] * pd.Series(range(n)).astype(float) / 1000
    df["volume"] = 1000 + pd.Series(range(n))
    return df

def _apply(name, df, params=None):
    """apply_factor 的便捷封装：get_factor 返回 (defn, merged, fp)，显式解构避免参数错位。"""
    defn, merged, _ = get_factor(name, params)
    return apply_factor(defn, df, merged)

def test_apply_ma_matches_indicators():
    df = _df()
    out = _apply("ma", df, {"n": 5})
    pd.testing.assert_series_equal(out, ind.ma(df["close"], 5), check_names=False)

def test_apply_rsi_matches_indicators():
    df = _df()
    out = _apply("rsi", df)
    pd.testing.assert_series_equal(out, ind.rsi(df["close"], 14), check_names=False)

def test_apply_macd_hist_matches_indicators():
    df = _df()
    dif, dea, hist = ind.macd(df["close"])
    out = _apply("macd_hist", df)
    pd.testing.assert_series_equal(out, hist, check_names=False)

def test_apply_kdj_j_and_boll_match():
    df = _df()
    _, _, j = ind.kdj(df)
    pd.testing.assert_series_equal(_apply("kdj_j", df), j,
                                   check_names=False)          # 头段 NaN 按相等处理
    mid, up, low = ind.boll(df["close"])
    pd.testing.assert_series_equal(_apply("boll_up", df), up, check_names=False)

def test_vol_ratio_manual():
    df = _df()
    out = _apply("vol_ratio", df, {"n": 5})
    # NaN 头：.all() 在 NaN==NaN 处必然 False，用 assert_series_equal（NaN-safe 相等）
    pd.testing.assert_series_equal(out, df["volume"] / df["volume"].rolling(5).mean(),
                                   check_names=False)

def test_mom_manual():
    df = _df()
    pd.testing.assert_series_equal(_apply("mom", df, {"n": 5}), df["close"].pct_change(5),
                                   check_names=False)

def test_bias_manual():
    df = _df()
    m = ind.ma(df["close"], 20)
    pd.testing.assert_series_equal(_apply("bias", df), (df["close"] - m) / m,
                                   check_names=False)

def test_missing_input_raises():
    df = _df().drop(columns=["volume"])
    with pytest.raises(FactorInputError):
        _apply("vol_ratio", df)
```

- [x] **Step 2: 运行确认失败** → `pytest tests/test_factor_compute.py -v`，预期 FAIL（模块/因子未定义）
- [x] **Step 3: 实现** `src/factors/compute.py` + `src/factors/factors.py`

```python
# compute.py
from factors.registry import FactorDefinition, FactorInputError

def apply_factor(defn: FactorDefinition, df, params: dict):
    missing = [c for c in defn.inputs if c not in df.columns]
    if missing:
        raise FactorInputError(f"{defn.name}: 缺输入列 {missing}（需要 {list(defn.inputs)}）")
    return defn.fn(df, **params)
```

```python
# factors.py —— import 即注册。指标引用 backtest.indicators，条件因子用 pandas 滚动算子
import backtest.indicators as ind
from factors.registry import register_factor

@register_factor("ma", inputs=("close",), default_params={"n": 20},
                 lookback=lambda p: p["n"],   # 滚动类尾部缺口补算需 lookback seed
                 doc="N日简单均线。同花顺条件句：MA5>MA20、收盘价>MA20 等")
def _ma(df, n=20): return ind.ma(df["close"], n)

@register_factor("ema", inputs=("close",), default_params={"n": 12},
                 doc="N日指数均线。同花顺：EMA5、收盘价>EMA20 等")   # ewm 无窗口期，lookback=0 默认
def _ema(df, n=12): return ind.ema(df["close"], n)

@register_factor("rsi", inputs=("close",), default_params={"n": 14},
                 lookback=lambda p: p["n"],
                 doc="RSI(Wilder)。同花顺：RSI>70、RSI<30 等超买超卖条件")
def _rsi(df, n=14): return ind.rsi(df["close"], n)

@register_factor("atr", inputs=("high", "low", "close"), default_params={"n": 14},
                 lookback=lambda p: p["n"],
                 doc="平均真实波幅。同花顺：无直接对应，用于波动过滤")
def _atr(df, n=14): return ind.atr(df, n)

@register_factor("macd_hist", inputs=("close",),
                 default_params={"fast": 12, "slow": 26, "signal": 9},
                 doc="MACD 柱(国内惯例 2*(dif-dea))。同花顺：MACD柱>0、红柱放大")   # ewm 无窗口期，lookback=0 默认
def _macd_hist(df, fast=12, slow=26, signal=9): return ind.macd(df["close"], fast, slow, signal)[2]

@register_factor("kdj_j", inputs=("high", "low", "close"), default_params={"n": 9},
                 lookback=lambda p: p["n"],
                 doc="KDJ 的 J 值。同花顺：J>100 超买、J<0 超卖")
def _kdj_j(df, n=9): return ind.kdj(df, n)[2]

@register_factor("boll_up", inputs=("close",), default_params={"n": 20, "k": 2},
                 lookback=lambda p: p["n"],
                 doc="布林上轨。同花顺：收盘价>BOLL上轨（突破）")
def _boll_up(df, n=20, k=2): return ind.boll(df["close"], n, k)[1]

@register_factor("boll_low", inputs=("close",), default_params={"n": 20, "k": 2},
                 lookback=lambda p: p["n"],
                 doc="布林下轨。同花顺：收盘价<BOLL下轨（超跌）")
def _boll_low(df, n=20, k=2): return ind.boll(df["close"], n, k)[2]

@register_factor("vol_ratio", inputs=("volume",), default_params={"n": 5},
                 lookback=lambda p: p["n"],
                 doc="量比：当日量/近n日均量。同花顺：量比>1.5（放量）")
def _vol_ratio(df, n=5): return df["volume"] / df["volume"].rolling(n).mean()

@register_factor("mom", inputs=("close",), default_params={"n": 5},
                 lookback=lambda p: p["n"],
                 doc="N日动量/涨幅。同花顺：5日涨幅>10%")
def _mom(df, n=5): return df["close"].pct_change(n)

@register_factor("bias", inputs=("close",), default_params={"n": 20},
                 lookback=lambda p: p["n"],
                 doc="乖离率：(收盘-均线)/均线。同花顺：BIAS20 超买超卖")
def _bias(df, n=20):
    m = ind.ma(df["close"], n)
    return (df["close"] - m) / m
```

注意：`ind.boll(close, n, k)` 返回 `(mid, up, low)` 三元组；`kdj` 返回 `(k, d, j)`。若实际签名不同，以 `backtest/indicators.py` 为准微调（`_df` 中价格已有变化，滚动值非平凡，对拍有效）。`lookback` 只影响尾部缺口补算的取数前移，不进指纹、不进 factor.json。
- [x] **Step 4: 运行确认通过** → `pytest tests/test_factor_compute.py -v`，PASS（若 boll 签名不符，读 `indicators.py` 修正后重跑）
- [ ] **Step 5: Commit**（不执行，保持未勾）

## Task 3: FactorStore 存储与惰性取数（store.py）

**Files:**
- Create: `src/factors/store.py`
- Modify: `src/factors/__init__.py`（导出 FactorStore）
- Test: `tests/test_factor_store.py`

**Consumes:** Task 1 `get_factor`/异常、Task 2 `apply_factor`；`dc.get_klines(symbol, period, start_ms, end_ms, adjust=...)`（鸭子类型，见 test_engine.FakeDC）。
**Produces:** `FactorStore`（Task 4 消费）。

- [x] **Step 1: 写失败测试** `tests/test_factor_store.py`

```python
import pandas as pd
import pytest
import factors.factors  # noqa: F401
from factors.store import FactorStore

BAR_COLS = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]

def kdf(symbol, t0, closes, vols=None):
    n = len(closes); vols = vols or [1000 + i for i in range(n)]
    return pd.DataFrame({"symbol": [symbol]*n, "timestamp": [t0 + i for i in range(n)],
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": vols})

class FakeDC:
    def __init__(self, data): self.data = data; self.calls = []
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        df = self.data.get(symbol, pd.DataFrame(columns=BAR_COLS))
        if start_ms is not None: df = df[df["timestamp"] >= start_ms]
        if end_ms is not None:   df = df[df["timestamp"] <= end_ms]
        self.calls.append((symbol, start_ms, end_ms))
        return df.copy()

CLOSES = [10 + ((i * 7) % 13) / 10 for i in range(60)]  # 非单调，波动可用

@pytest.fixture
def dc(tmp_path):
    d = FakeDC({"a.SH": kdf("a.SH", 100, CLOSES)})
    return d

def test_first_get_computes_and_persists(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(out) == 60 and len(dc.calls) == 1
    parts = list((tmp_path / "f").rglob("part.parquet"))
    assert len(parts) == 1  # 已落盘

def test_second_get_hits_cache(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    a = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    b = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(dc.calls) == 1            # 二次命中，不重算
    # NaN 相等用 assert_series_equal（NaN==NaN → False，.all() 在 warmup NaN 处恒 False）
    pd.testing.assert_series_equal(a, b, check_names=False)

def test_gap_only_fetches_tail(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 120)
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert len(out) == 60
    assert dc.calls[0] == ("a.SH", 100, 120)   # 首查
    assert dc.calls[1] == ("a.SH", 116, 159)   # 尾缺口 + lookback(ma n=5)=5 前移取数；不重算已覆盖区
    from backtest.indicators import ma
    expect = ma(pd.Series(CLOSES), 5)          # 全窗口现算 = 已存头 + 补算尾
    # out 索引=timestamp（spec 要求），expect 为 0..59 RangeIndex；按位置对拍。
    # lookback seed 使缺口起始（pos 21 起）即满窗 → 平移不变滚动因子全窗逐根等价于现算
    # （check_index=False）；真实窗口头 warmup NaN 两边都有，assert_series_equal NaN-safe 通过。
    # 注：递推平滑因子（rsi/kdj/atr）为 seed 收敛近似，此处用 ma 断言精确等价。
    pd.testing.assert_series_equal(out, expect, check_names=False, check_index=False)

def test_no_lookahead(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    out = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    from backtest.indicators import ma
    # 值只依赖 ≤i 的数据：整段预取结果在 i 处 == 只用 [0..i] 现算
    for i in range(4, 60):
        prefix = pd.Series(CLOSES[:i + 1])
        assert out.iloc[i] == pytest.approx(ma(prefix, 5).iloc[-1])

def test_version_bump_recomputes(tmp_path, dc):
    from dataclasses import replace
    from factors.registry import REGISTRY
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    orig = REGISTRY["ma"]
    REGISTRY["ma"] = replace(orig, version=2)     # 模拟定义变更（公式/口径）
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    dirs = [p for p in (tmp_path / "f").iterdir() if p.is_dir()]
    assert len(dirs) == 2                          # 新指纹新目录，旧值保留
    REGISTRY["ma"] = orig                          # 还原

def test_refresh_overwrites(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    a = fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    dc.data["a.SH"]["close"] = [x + 100 for x in CLOSES]  # 底层数据变了
    b = fs.refresh("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    assert (a.iloc[20:] != b.iloc[20:]).any()      # 跳过 warmup NaN，值确实刷新

def test_drop_removes_dir(tmp_path, dc):
    fs = FactorStore(dc, root=tmp_path / "f")
    fs.get("a.SH", "ma", {"n": 5}, "1d", 100, 159)
    fs.drop("ma", {"n": 5})
    assert not list((tmp_path / "f").rglob("part.parquet"))
```

- [x] **Step 2: 运行确认失败** → `pytest tests/test_factor_store.py -v`，预期 FAIL（模块不存在）
- [x] **Step 3: 实现** `src/factors/store.py`

```python
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

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
        return self._fp_dir(fingerprint) / f"symbol={symbol}" / f"period={period}" / "part.parquet"

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
    def _lookback(self, defn, merged) -> int:
        lb = defn.lookback
        return lb(merged) if callable(lb) else int(lb or 0)

    def _fetch_compute(self, symbol, period, start_ms, end_ms, defn, params):
        df = self.dc.get_klines(symbol, period, start_ms, end_ms, adjust=self.adjust)
        if df is None or df.empty:
            return pd.Series(dtype=float, name=defn.name)
        df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        vals = apply_factor(defn, df, params)
        return pd.Series(vals.values, index=df["timestamp"].values, name=defn.name)

    def get(self, symbol, name, params=None, period="1d", start_ms=None, end_ms=None):
        if start_ms is None or end_ms is None:
            raise ValueError("start_ms/end_ms 必填")
        defn, merged, fp = get_factor(name, params, adjust=self.adjust)
        path = self._path(fp, symbol, period)
        stored = self._load(path)
        if not stored.empty and stored.index.min() <= start_ms and stored.index.max() >= end_ms:
            return stored.loc[start_ms:end_ms].rename(defn.name)   # 全覆盖，直接切片
        lo, hi = (int(stored.index.min()), int(stored.index.max())) if not stored.empty else (None, None)
        parts = []
        if lo is None:
            parts.append(self._fetch_compute(symbol, period, start_ms, end_ms, defn, merged))
        else:
            if start_ms < lo: parts.append(self._fetch_compute(symbol, period, start_ms, lo - 1, defn, merged))
            if end_ms > hi:
                # 尾缺口 lookback seed：向前多取 lookback 根 K 线算满窗，丢弃 seed 区只留缺口
                lb = self._lookback(defn, merged)
                tail = self._fetch_compute(symbol, period, max(start_ms, hi + 1 - lb), end_ms, defn, merged)
                parts.append(tail.loc[hi + 1:end_ms])
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
            shutil.rmtree(sym_dir / f"period={period}", ignore_errors=True)

    def warm(self, symbols, factors, period="1d", start_ms=None, end_ms=None, show_progress=False):
        total = len(symbols) * len(factors)
        done = 0
        for s in symbols:
            for f in factors:
                self.get(s, f, None, period, start_ms, end_ms)
                done += 1
                if show_progress: print(f"\r[{done}/{total}] {s} {f}", end="", flush=True)
        if show_progress: print()
```

实现要点（对齐 spec §6.2）：`stored.combine_first(new)` 重叠区以已存为准；缺口按"请求区间 \ 已存覆盖区间"拆成最多两段补算（`lo-1`/`hi+1` 毫秒边界）；**尾缺口补算前移 `defn.lookback` 根取数（`max(start_ms, hi+1-lookback)`）、算完丢弃 seed 区（`tail.loc[hi+1:end_ms]`）**——平移不变滚动因子缺口起始即满窗、与现算逐根相等；递推平滑因子（rsi/kdj/atr）为 seed 收敛近似（等价性边界见 spec §6.2）；空结果不落盘；原子写用临时文件 + `os.replace`。`factor.json` 快照可在测试后补（不影响取数正确性，见 Step 4 说明）。
- [x] **Step 4: 运行确认通过** → `pytest tests/test_factor_store.py -v`，PASS。若 `test_gap_only_fetches_tail` 失败，检查 `get()` 的缺口拆分与 `combine_first` 语义：`lo-1`/`hi+1` 毫秒边界是否正确、重叠区是否以已存为准（`stored.combine_first(new)`）。
- [ ] **Step 5: Commit**（不执行，保持未勾）

## Task 4: 双均线改造走因子库 + golden 对拍

**Files:**
- Modify: `examples/strategies/ma_cross.py`
- Modify: `examples/run_backtest.py`
- Test: `tests/test_ma_cross_factors.py`

**Consumes:** Task 3 `FactorStore`；`backtest.engine.BacktestEngine` / `backtest.performance.analyze`。
**Produces:** 改造后的 `MaCross(short, long, fs=None)`（规则逻辑不变，只换因子来源）。

- [x] **Step 1: 写失败测试（golden 对拍）** `tests/test_ma_cross_factors.py`

```python
import pandas as pd
from conftest import make_kline_df
from backtest.engine import BacktestEngine
from backtest.performance import analyze
from examples.strategies.ma_cross import MaCross
from factors.store import FactorStore

def kdf_with_crosses(symbol="a.SH", n=60):
    # 构造出现金叉/死叉的价格序列（正弦趋势 + 噪声），确保有交易
    import math
    closes = [round(10 + 3 * math.sin(i / 4.0) + (i % 7) * 0.1, 3) for i in range(n)]
    df = pd.DataFrame({"symbol": [symbol]*n, "timestamp": list(range(100, 100 + n)),
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "volume": [1000 + i for i in range(n)]})
    return df

class FakeDC:
    def __init__(self, df): self.df = df
    def get_klines(self, symbol, period="1d", start_ms=None, end_ms=None, adjust="forward"):
        d = self.df
        if start_ms is not None: d = d[d["timestamp"] >= start_ms]
        if end_ms is not None:   d = d[d["timestamp"] <= end_ms]
        return d.copy()

def _run(df, ma_cross):
    eng = BacktestEngine(FakeDC(df), ["a.SH"], period="1d",
                         start_ms=100, end_ms=100 + len(df) - 1)
    eng.run(ma_cross)
    return analyze(eng.broker, eng.data, period="1d")

def test_golden_factors_identical(tmp_path):
    df = kdf_with_crosses()
    orig = _run(df, MaCross(5, 20))                     # 现算版（原逻辑）
    refa = _run(df, MaCross(5, 20, fs=FactorStore(FakeDC(df), root=tmp_path / "f")))
    # 逐笔交易一致（时间/价格/股数/盈亏）
    assert [(t.buy_ts, t.sell_ts, t.shares, round(t.pnl, 2)) for t in orig.trades] == \
           [(t.buy_ts, t.sell_ts, t.shares, round(t.pnl, 2)) for t in refa.trades]
    # 总收益一致
    assert round(orig.total_return, 6) == round(refa.total_return, 6)
    # 二次运行命中缓存仍一致（复用路径）
    refb = _run(df, MaCross(5, 20, fs=FactorStore(FakeDC(df), root=tmp_path / "f")))
    assert refb.trade_count == refa.trade_count
```

- [x] **Step 2: 运行确认失败** → `pytest tests/test_ma_cross_factors.py -v`，预期 FAIL（`MaCross` 无 `fs` 参数）
- [x] **Step 3: 改造** `examples/strategies/ma_cross.py`

```python
"""示例策略：双均线金叉/死叉。因子值从 FactorStore 惰性取数（算一次存库，回测复用）。

- 快线（默认 5 日）上穿慢线（默认 20 日）-> 全仓买入；下穿 -> 清仓
- 滚动指标因果、无前视：init 一次性取整段因子序列，on_bar 按时间戳对齐
- fs 为 None 时行为不变（保持原现算路径，供测试/对比）
"""
from backtest.indicators import ma
from backtest.strategy import Strategy


class MaCross(Strategy):
    def __init__(self, short: int = 5, long: int = 20, fs=None):
        self.short = short
        self.long = long
        self.fs = fs

    def init(self, ctx) -> None:
        self.ma_s, self.ma_l = {}, {}
        if self.fs is None:
            return  # 无 fs：走 on_bar 现算路径（行为不变）
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if h.empty:
                continue
            ts = h["timestamp"]
            self.ma_s[symbol] = self.fs.get(symbol, "ma", {"n": self.short}, "1d",
                                            int(ts.min()), int(ts.max()))
            self.ma_l[symbol] = self.fs.get(symbol, "ma", {"n": self.long}, "1d",
                                            int(ts.min()), int(ts.max()))

    def on_bar(self, ctx) -> None:
        for symbol in ctx.symbols:
            h = ctx.history(symbol)
            if len(h) < self.long + 1:
                continue  # 慢线还没满窗口，不交易
            ts = h["timestamp"]
            if self.fs is not None:
                s = self.ma_s[symbol].loc[ts.iloc[-1]]
                l = self.ma_l[symbol].loc[ts.iloc[-1]]
                s_prev = self.ma_s[symbol].loc[ts.iloc[-2]]
                l_prev = self.ma_l[symbol].loc[ts.iloc[-2]]
            else:
                s_series = ma(h["close"], self.short)
                l_series = ma(h["close"], self.long)
                s, l = s_series.iloc[-1], l_series.iloc[-1]
                s_prev, l_prev = s_series.iloc[-2], l_series.iloc[-2]
            held = symbol in ctx.positions
            if s_prev <= l_prev and s > l:      # 金叉
                ctx.buy(symbol)                  # shares=None 全仓
            elif held and s_prev >= l_prev and s < l:  # 死叉
                ctx.sell(symbol)
```

`examples/run_backtest.py`：`from factors import FactorStore`，两处 `eng.run(MaCross(5, 20))` → `eng.run(MaCross(5, 20, fs=FactorStore(dc)))`，并在模块 docstring 注明"首次运行计算因子落盘 data/factors/，再次运行命中缓存"。
- [x] **Step 4: 运行确认通过** → `pytest tests/test_ma_cross_factors.py -v`，PASS；`source ~/.zshrc && .venv/bin/python -m examples.run_backtest` 真实数据跑通（600000.SH 单标的 + 多标的），首跑落盘、二跑命中缓存
- [ ] **Step 5: Commit**（不执行，保持未勾）

## Task 5: 收尾（factor_warm.py + README + 回归）

**Files:**
- Create: `scripts/factor_warm.py`
- Modify: `README.md`
- Test: 全量回归

- [x] **Step 1: 实现批量预热脚本** `scripts/factor_warm.py`

```python
"""因子库批量预热：FactorStore.warm 对指定标的×因子算一遍入库，之后回测直接命中缓存。
运行：source ~/.zshrc && .venv/bin/python scripts/factor_warm.py --symbols 600000.SH,000001.SZ --factors ma,vol_ratio --years 5
"""
import argparse, time
from datacenter import DataCenter
from factors import FactorStore
import factors.factors  # noqa: F401 注册内置因子

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True, help="逗号分隔")
    ap.add_argument("--factors", default="ma,ema,rsi,macd_hist,kdj_j,boll_up,boll_low,vol_ratio,mom,bias")
    ap.add_argument("--period", default="1d")
    ap.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    end = int(time.time() * 1000)
    start = end - a.years * 365 * 86_400_000
    fs = FactorStore(DataCenter())
    fs.warm(a.symbols.split(","), a.factors.split(","), a.period, start, end, show_progress=True)

if __name__ == "__main__":
    main()
```

- [x] **Step 2: README 补充**——因子库一节：`src/factors/` 三模块职责、`FactorStore.get` 惰性取数用法、内置因子清单与同花顺条件句映射、`factor_warm.py` 预热、双均线示例已走因子库。
- [x] **Step 3: 全量回归** → `.venv/bin/python -m pytest tests/`，预期全绿（既有 ~126 + 新增 ~30）
- [x] **Step 4: 计划 checkbox 入库**——本计划已勾选步骤随实现入库；Commit 步骤保持未勾
- [ ] **Step 5: Commit**（不执行，保持未勾）

## 关键复用

- 指标公式：`src/backtest/indicators.py`（`ma/ema/rsi/macd/kdj/atr/boll`）
- 惰性取数先例：`src/datacenter/resolver.py` 的 CacheResolver（本地优先、缺失回源）
- parquet 分区/原子写先例：`src/datacenter/store/klines.py`
- 测试基建：`tests/conftest.py` 的 `make_kline_df`；`tests/test_engine.py` 的 `FakeDC` 鸭子类型 + `kdf` 合成 K 线
- 门面：`DataCenter.get_klines(symbol, period, start_ms, end_ms, adjust="forward")`
- 计划/规格：spec `docs/superpowers/specs/2026-08-30-factor-library-design.md`
