"""因子定义注册表。

以装饰器方式注册因子定义（名称、类别、周期、版本、输入字段、默认参数、
说明文档），并提供按名查询（合并默认参数 + 校验未知参数）与指纹计算。

Task 2/3 的因子计算与存储依赖本模块导出的
`FactorDefinition` / `register_factor` / `get_factor` / `list_factors` /
`FactorError` 异常族。
"""
import hashlib, json
from dataclasses import dataclass, field
from typing import Callable

__all__ = ["FactorDefinition", "register_factor", "get_factor", "list_factors",
           "FactorError", "FactorUnknownError", "FactorParamError", "FactorInputError"]

class FactorError(Exception): ...
class FactorUnknownError(FactorError): ...
class FactorParamError(FactorError): ...
class FactorInputError(FactorError): ...

@dataclass(frozen=True)
class FactorDefinition:
    """因子定义：注册元数据 + 计算函数。"""
    name: str
    fn: Callable
    category: str = "price-volume"
    period: str = "1d"
    version: int = 1
    inputs: tuple[str, ...] = ("close",)
    default_params: dict = field(default_factory=dict)
    doc: str = ""
    lookback: int | Callable[[dict], int] = 0   # 尾部缺口补算时向前预取的 seed 根数；int 或 (merged_params)->int

REGISTRY: dict[str, FactorDefinition] = {}

def register_factor(name, *, category="price-volume", period="1d", version=1,
                    inputs=("close",), default_params=None, doc="", lookback=None):
    inputs = (inputs,) if isinstance(inputs, str) else tuple(inputs)
    def deco(fn):
        REGISTRY[name] = FactorDefinition(name=name, category=category, period=period,
                                          version=version, inputs=inputs,
                                          default_params=dict(default_params or {}),
                                          doc=doc, lookback=lookback or 0, fn=fn)
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
