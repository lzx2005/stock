"""策略模块（strategy module）。

在行情模块、因子模块之后的一层：存储策略名称、策略方案、回测记录、
回测结果，含版本管理（每次回测 = 新版本）与跨版本对比（新版本同时
对比 v1 原始版与上一版，判断"有没有进度"）。

镜像 `src/factors/` 的目录式 JSON 存储风格。本包不 import 任何注册表，
不依赖 DataCenter（纯文件系统）。
"""
from strategy.errors import StrategyError, StrategyNotFoundError, VersionNotFoundError
from strategy.store import StrategyStore

__all__ = ["StrategyStore", "StrategyError", "StrategyNotFoundError", "VersionNotFoundError"]
