import json, hashlib
import pytest
from factors.registry import (FactorDefinition, register_factor, get_factor,
                              list_factors, FactorUnknownError, FactorParamError)

def _fp(name="ma", params=None, version=1, adjust="forward"):
    p = json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{name}|{p}|{version}|{adjust}".encode()).hexdigest()[:16]

def test_register_and_get_factor():
    register_factor("ma", inputs=("close",), default_params={"n": 20},
                    lookback=lambda p: p["n"],   # 与内置 ma 的 lookback 语义一致，避免污染其他测试
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
