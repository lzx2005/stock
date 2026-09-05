"""因子库（factor library）包。

当前导出因子定义注册表相关符号（Task 1）；Task 3 将在此基础上加入
FactorStore 因子存储。注意：本包不 import `factors.factors`（避免测试污染，
由使用方显式 import）。
"""
from factors.registry import *
from factors.store import FactorStore
