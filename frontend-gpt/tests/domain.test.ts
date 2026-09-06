import { describe, it, expect, vi } from "vitest";
import {
  movingAverage,
  dateRange,
  validateTask,
  loadBars,
} from "../src/domain";

describe("行情与任务边界", () => {
  it("均线预热为空，且只使用当时和过去的数据", () => {
    expect(movingAverage([1, 2, 3, 100], 3)).toEqual([null, null, 2, 35]);
  });
  it("日期范围以中国时区覆盖完整终止日", () => {
    expect(dateRange("2026-09-01", "2026-09-02")).toEqual({
      start_ms: Date.parse("2026-09-01T00:00:00+08:00"),
      end_ms: Date.parse("2026-09-02T23:59:59.999+08:00"),
    });
    expect(() => dateRange("2026-09-03", "2026-09-01")).toThrow();
  });
  it("拦截空白字段与小于60秒或非法轮询间隔", () => {
    expect(
      Object.keys(
        validateTask({ name: " ", symbol: "", script: "", interval_sec: 20 }),
      ),
    ).toHaveLength(4);
    expect(
      validateTask({
        name: "test",
        symbol: "600000.SH",
        script: "def check(ctx): pass",
        interval_sec: 60,
      }),
    ).toEqual({});
  });
  it("图表读取超过2000根的完整区间，并保留回源警告", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        total: 2001,
        rows: Array.from({ length: 2000 }, (_, i) => [i, 1, 2, 0, 1, 2, 2]),
        refresh_error: "离线",
      })
      .mockResolvedValueOnce({ total: 2001, rows: [[2000, 1, 2, 0, 1, 2, 2]] });
    const data = await loadBars(
      request,
      { symbol: "600000.SH", period: "1d" },
      true,
      new AbortController().signal,
    );
    expect(data.rows).toHaveLength(2001);
    expect(data.refresh_error).toBe("离线");
    expect(request.mock.calls[1][1].page).toBe(2);
  });
});

it("带截止日的回源结果保留盘中 bar 并裁掉区间以外的行", async () => {
  const request = vi.fn().mockResolvedValue({
    total: 3,
    refreshed: true,
    rows: [
      [100, 1, 2, 0, 1, 2, 2],
      [200, 1, 2, 0, 1, 2, 2],
      [300, 1, 2, 0, 1, 2, 2],
    ],
  });
  const result = await loadBars(
    request,
    { start_ms: 100, end_ms: 200 },
    true,
    new AbortController().signal,
  );
  expect(result.rows.map((r) => r[0])).toEqual([100, 200]);
  expect(result.refreshed).toBe(true);
});
