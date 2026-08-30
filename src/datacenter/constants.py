ALL_PERIODS = ["1m", "5m", "10m", "15m", "30m", "60m", "1d", "1w", "1M", "1Q", "1Y"]
MINUTE_PERIODS = {"1m", "5m", "15m", "30m", "60m"}  # 套餐不含 10m；10m 需要时由 5m 聚合
BACKFILL_ORDER = ["1d", "1w", "1M", "1Q", "1Y", "60m", "30m", "15m", "5m", "1m"]  # 先粗后细
MAX_PAGE = 5000  # 分钟接口单次上限 5000 条（日线文档上限 10000，统一取保守值）
MINUTE_HISTORY_DAYS = 365   # 套餐硬限制：分钟线仅最近 365 天
DAILY_HISTORY_DAYS = 3 * 365
