"""盯盘脚本注册前验证管线：语法检查 → 真实干跑 → 历史回放（盯盘专家 skill 用）。

用法（项目根目录）：
    source ~/.zshrc    # 必须：非交互 shell 拿不到 TICKFLOW_API_KEY，干跑/回放回源会失败
    .venv/bin/python scripts/validate_watch.py <script.py> <symbol> [--days 750]

输出三段：
    1. 语法 OK（compile 检查，不执行）
    2. 干跑返回值（用真实 DataCenter 构造当前 ctx 跑一次 check，打印 on/msg）
    3. 历史回放：近 --days 个自然日内逐交易日评估，打印触发次数 + 最近 3 次触发日期

回放口径（日线近似 ctx）：asof 移到当日收盘 15:00（日K 时间戳是当日 00:00，
直接当 asof 分钟窗口会退化为空），price=当日收盘（分钟为空时回放模式兜底
取当日日K 收盘，全时段可用）、daily(n)=截至当日窗口、factor 同口径；
minute_bars 依赖 1m 缓存（仅 1 年深度），更早日期返回空 df——只有依赖分钟线
细节的脚本在这些日期回放行为偏离真实盘中。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # 防 scripts/ 下同名脚本遮蔽 monitor 包

from monitor.runtime import DataError, MonitorContext, run_check

_DAY_MS = 86_400_000


def compile_check(script: str) -> None:
    """语法检查；失败抛 SyntaxError。"""
    compile(script, "<watch-script>", "exec")


def _day_key(ts_ms: int) -> tuple[int, int, int]:
    t = time.localtime(ts_ms / 1000)
    return (t.tm_year, t.tm_mon, t.tm_mday)


def _day_start_ms(ts_ms: int) -> int:
    t = time.localtime(ts_ms / 1000)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def replay_daily(script: str, symbol: str, dc, fs, days: int = 750) -> list[int]:
    """逐日评估 check，返回触发（buy 或 sell 为 True）的日期 ms 列表（当日 0 点）。"""
    now_ms = int(time.time() * 1000)
    df = dc.get_klines(symbol, "1d", now_ms - days * _DAY_MS, now_ms, adjust="forward")
    if df is None or len(df) == 0:
        return []
    # 按本地交易日分组，取每交易日最后一根 bar 的时间戳
    day_ends: dict[tuple[int, int, int], int] = {}
    for ts in sorted(int(t) for t in df["timestamp"]):
        day_ends[_day_key(ts)] = ts
    hits: list[int] = []
    for key in sorted(day_ends)[-days:]:
        bar_ts = day_ends[key]
        # 日K 时间戳=当日 00:00，asof 移到当日收盘 15:00（否则 minute_bars 窗口
        # 退化为 [00:00, 00:00]，price() 必抛 DataError）
        ctx = MonitorContext(dc, fs, symbol, asof_ms=bar_ts + 15 * 3_600_000)
        try:
            out = run_check(script, ctx)
        except DataError:
            continue  # 当日无数据（停牌/分钟缓存超 1 年深度），按未触发处理
        if out.get("on") is True:
            hits.append(_day_start_ms(bar_ts))
    return hits


def _fmt_day(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts_ms / 1000))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="validate_watch",
                                description="盯盘脚本注册前验证：语法 → 干跑 → 历史回放")
    p.add_argument("script", help="脚本文件路径（定义 check(ctx)）")
    p.add_argument("symbol", help="标的，如 600869.SH")
    p.add_argument("--days", type=int, default=750, help="回放窗口（自然日，默认 750≈3 年）")
    args = p.parse_args(argv)

    script = Path(args.script).read_text(encoding="utf-8")

    # 第 1 段：语法检查
    compile_check(script)
    print("语法 OK")

    # 第 2 段：真实干跑（需 source ~/.zshrc 拿到 TICKFLOW_API_KEY）
    import factors.factors  # noqa: F401  显式注册内置因子
    from datacenter import DataCenter
    from factors import FactorStore

    dc = DataCenter()
    fs = FactorStore(dc)
    ctx = MonitorContext(dc, fs, args.symbol)
    out = run_check(script, ctx)
    print(f"干跑返回值: on={out['on']} msg={out['msg']}")

    # 第 3 段：历史回放
    hits = replay_daily(script, args.symbol, dc, fs, days=args.days)
    print(f"回放触发次数: {len(hits)}（近 {args.days} 个自然日）")
    if hits:
        recent = "、".join(_fmt_day(t) for t in hits[-3:])
        print(f"最近 3 次触发日期: {recent}")


if __name__ == "__main__":
    main()
