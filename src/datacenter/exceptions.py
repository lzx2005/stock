class DataCenterError(Exception):
    """数据中心异常基类"""


class DataUnavailableError(DataCenterError):
    """本地无数据且回源失败"""


class TickFlowError(DataCenterError):
    """数据源调用失败（重试耗尽或不可重试错误）"""


class RateLimitError(TickFlowError):
    """数据源限流（重试耗尽后抛出）"""
