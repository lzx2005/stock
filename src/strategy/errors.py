"""策略模块异常族。"""


class StrategyError(Exception):
    """策略模块通用错误。"""


class StrategyNotFoundError(StrategyError):
    """策略不存在。"""


class VersionNotFoundError(StrategyError):
    """策略版本不存在。"""
