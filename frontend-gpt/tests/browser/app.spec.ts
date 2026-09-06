import { test, expect, type Page } from "@playwright/test";
const start = Date.parse("2026-01-01T15:00:00+08:00");
const bars = Array.from({ length: 2505 }, (_, i) => {
  const open = +(10 + i * 0.002 + Math.sin(i / 7) * 0.4).toFixed(2);
  const close = +(open + Math.sin(i * 2.4) * 0.15).toFixed(2);
  return [
    start + i * 60000,
    open,
    Math.max(open, close) + 0.15,
    Math.min(open, close) - 0.13,
    close,
    2500000 + i * 1000,
    25000000,
  ];
});
const coverage = [
  {
    symbol: "600000.SH",
    code: "600000",
    name: "浦发银行",
    period: "1d",
    start_ms: start,
    end_ms: bars.at(-1)![0],
    updated_at: start / 1000,
  },
  {
    symbol: "600000.SH",
    code: "600000",
    name: "浦发银行",
    period: "1m",
    start_ms: start,
    end_ms: bars.at(-1)![0],
    updated_at: start / 1000,
  },
  {
    symbol: "000001.SZ",
    code: "000001",
    name: "平安银行",
    period: "1d",
    start_ms: start,
    end_ms: bars.at(-1)![0],
    updated_at: start / 1000,
  },
];
const firstTask = {
  id: 1,
  name: "均线趋势观察",
  symbol: "600000.SH",
  description: "观察均线向上突破，满足条件时亮灯。",
  script: 'def check(ctx):\n    return {"on": True, "msg": "观察"}',
  interval_sec: 60,
  enabled: 1,
  notify: 1,
  lamp_on: 1,
  poll_count: 128,
  signal_count: 3,
  error_count: 0,
  last_error: null,
  last_run_at: Date.now(),
  created_at: start,
};
async function fixtures(page: Page, refreshError = false) {
  const calls: {
    path: string;
    method: string;
    query: URLSearchParams;
    body: any;
  }[] = [];
  let tasks = [{ ...firstTask }];
  let delayNextGet: (() => Promise<void>) | null = null;
  await page.route("https://picsum.photos/**", (route) => route.abort());
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.searchParams;
    const path = url.pathname;
    const method = req.method();
    const body = req.postDataJSON();
    calls.push({ path, method, query: p, body });
    const send = (data: unknown, status = 200) =>
      route.fulfill({ json: data, status });
    const pageNum = Number(p.get("page") || 1),
      size = Number(p.get("size") || 50);
    if (path === "/api/periods") return send({ items: ["1m", "1d", "1w"] });
    if (path === "/api/coverage") {
      const rows = coverage.filter(
        (r) =>
          (!p.get("period") || r.period === p.get("period")) &&
          (!p.get("q") || `${r.name}${r.symbol}`.includes(p.get("q")!)),
      );
      return send({
        total: rows.length,
        items: rows.slice((pageNum - 1) * size, pageNum * size),
        page: pageNum,
        size,
      });
    }
    if (path === "/api/klines") {
      const refresh = p.get("refresh") === "1";
      const rows = bars.filter(
        (r) =>
          (!p.get("start_ms") || r[0] >= Number(p.get("start_ms"))) &&
          (refresh || !p.get("end_ms") || r[0] <= Number(p.get("end_ms"))),
      );
      return send({
        rows: rows.slice((pageNum - 1) * size, pageNum * size),
        total: rows.length,
        refreshed: refresh && !refreshError,
        refresh_error: refresh && refreshError ? "测试回源失败" : null,
      });
    }
    if (path === "/api/factors")
      return send({
        total: 2,
        items: [
          {
            name: "ma",
            default_params: { n: 20 },
            version: 1,
            category: "trend",
            doc: "简单移动平均线：收盘价 > MA20",
            stored_dir_count: 1,
          },
          {
            name: "rsi",
            default_params: { n: 14 },
            version: 1,
            category: "momentum",
            doc: "相对强弱指标",
            stored_dir_count: 0,
          },
        ],
      });
    if (path === "/api/factor-dirs")
      return send({
        total: 1,
        items: [
          {
            fingerprint: "ma-fingerprint",
            name: "ma",
            params: { n: 20 },
            version: 1,
            adjust: "forward",
            cells: [{ symbol: "600000.SH", period: "1d", rows: 75 }],
            total_rows: 75,
          },
        ],
      });
    if (path === "/api/factor-values")
      return send({
        total: 75,
        rows: Array.from({ length: 75 }, (_, i) => [
          start + i * 86400000,
          i === 0 ? null : 10 + i / 10,
        ]).slice((pageNum - 1) * size, pageNum * size),
      });
    if (path === "/api/monitor/tasks" && method === "GET") {
      const snapshot = tasks.map((t) => ({ ...t }));
      const wait = delayNextGet;
      delayNextGet = null;
      if (wait) await wait();
      return send({ items: snapshot });
    }
    if (path === "/api/monitor/tasks" && method === "POST") {
      const task = { ...firstTask, ...body, id: 2 };
      tasks.push(task);
      return send({ id: 2 });
    }
    if (path.endsWith("/toggle")) {
      const task = tasks.find((t) => path.includes(`/${t.id}/`))!;
      task.enabled = task.enabled ? 0 : 1;
      return send({ enabled: task.enabled });
    }
    if (path.match(/\/monitor\/tasks\/\d+$/)) {
      const id = Number(path.split("/").at(-1));
      if (method === "DELETE") tasks = tasks.filter((t) => t.id !== id);
      else tasks = tasks.map((t) => (t.id === id ? { ...t, ...body } : t));
      return send({ ok: true });
    }
    if (path === "/api/monitor/signals")
      return send({
        items: Array.from({ length: 103 }, (_, i) => ({
          id: 103 - i,
          task_id: 1,
          ts: Date.now() - i * 60000,
          kind: i === 2 ? "buy_on" : i % 2 ? "off" : "on",
          price: 12.3,
          message: `观察条件变化 ${i}`,
        })).slice(0, Number(p.get("limit") || 200)),
      });
    return send({ detail: "Unknown fixture" }, 404);
  });
  return {
    calls,
    delayGet: (fn: () => Promise<void>) => {
      delayNextGet = fn;
    },
  };
}
const selectMarket = async (page: Page) => {
  await page
    .locator(".instrument")
    .filter({ hasText: "浦发银行" })
    .first()
    .click();
  await expect(page.getByRole("img", { name: /2505 根/ })).toBeVisible();
};

test("标的归组、详情切周期、完整区间与缓存警告", async ({ page }) => {
  const { calls } = await fixtures(page, true);
  await page.goto("/");
  await page.getByLabel("行情周期", { exact: true }).selectOption("");
  await expect(page.locator(".instrument")).toHaveCount(2);
  await selectMarket(page);
  await expect(page.getByText(/测试回源失败/).first()).toBeVisible();
  await page.getByLabel("详情周期").selectOption("1m");
  await expect(page.getByRole("img", { name: /2505 根 1m/ })).toBeVisible();
  expect(
    calls.some(
      (c) =>
        c.path === "/api/klines" &&
        c.query.get("page") === "2" &&
        c.query.get("size") === "2000",
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "折叠标的列表" }).click();
  await expect(
    page.getByRole("button", { name: "展开标的列表" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: /因子/ }).click();
  await page.getByRole("tab", { name: /行情/ }).click();
  await expect(page.getByLabel("详情周期")).toHaveValue("1m");
  await expect(
    page.getByRole("button", { name: "展开标的列表" }),
  ).toBeVisible();
});

test("日期查询与取最新都保留指定范围，明细服务端分页", async ({ page }) => {
  const { calls } = await fixtures(page);
  await page.goto("/");
  await selectMarket(page);
  await page.getByLabel("开始日期").fill("2026-01-01");
  await page.getByLabel("结束日期").fill("2026-01-01");
  await page.getByRole("button", { name: "查询", exact: true }).click();
  await expect(page.getByRole("img", { name: /540 根/ })).toBeVisible();
  await page.getByRole("button", { name: "取最新", exact: true }).click();
  await expect(page.getByRole("img", { name: /540 根/ })).toBeVisible();
  await page
    .locator(".market-page .data-block")
    .getByLabel("每页条数")
    .selectOption("50");
  await expect(page.locator(".market-page .data-block tbody tr")).toHaveCount(
    50,
  );
  await page.locator(".market-page .data-block").getByLabel("下一页").click();
  await expect
    .poll(() =>
      calls.some(
        (c) =>
          c.path === "/api/klines" &&
          c.query.get("page") === "2" &&
          c.query.get("size") === "50",
      ),
    )
    .toBeTruthy();
});

test("因子四级下钻、空目录、null 值与分页状态保持", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  await page.getByRole("tab", { name: /因子/ }).click();
  await page.getByRole("row").filter({ hasText: "rsi" }).click();
  await expect(page.getByText("这个因子还没有已存数据")).toBeVisible();
  await page.getByRole("button", { name: "全部因子", exact: true }).click();
  await page.getByRole("row").filter({ hasText: "ma" }).click();
  await page.getByRole("row").filter({ hasText: "ma-fingerprint" }).click();
  await page.getByRole("row").filter({ hasText: "600000.SH" }).click();
  await expect(page.locator(".factor-block tbody tr").first()).toContainText(
    "—",
  );
  await page.locator(".factor-block").getByLabel("下一页").click();
  await expect(page.locator(".factor-block tbody tr")).toHaveCount(25);
  await page.getByRole("tab", { name: /行情/ }).click();
  await page.getByRole("tab", { name: /因子/ }).click();
  await expect(page.locator(".factor-block .pagination")).toContainText(
    "2 / 2",
  );
});

test("盯盘单灯、历史事件兜底、新建校验、编辑、启停、删除确认", async ({
  page,
}) => {
  const { calls } = await fixtures(page);
  await page.goto("/");
  await page.getByRole("tab", { name: /盯盘/ }).click();
  await expect(
    page.getByRole("columnheader", { name: "信号灯", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".monitor-table .lamp.lit")).toHaveCount(1);
  await expect(page.getByText("buy_on", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  await page.getByRole("button", { name: "保存任务" }).click();
  await expect(page.getByText("请输入任务名称")).toBeVisible();
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  await page.getByLabel("任务名称").fill("回归测试任务");
  await page.getByLabel("标的代码").fill("000001.SZ");
  await expect(page.getByLabel("盯盘脚本", { exact: true })).toHaveValue(
    /"on": False/,
  );
  await page.getByRole("button", { name: "保存任务" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("row").filter({ hasText: "回归测试任务" }),
  ).toBeVisible();
  await page
    .getByRole("row")
    .filter({ hasText: "回归测试任务" })
    .getByRole("button", { name: "详情" })
    .click();
  await page.getByLabel("任务说明").fill("已编辑的说明");
  await page.getByRole("button", { name: "保存任务" }).click();
  await expect(page.getByText("已编辑的说明")).toBeVisible();
  await page.getByRole("switch", { name: "启用 回归测试任务" }).click();
  await expect(
    page.getByRole("switch", { name: "启用 回归测试任务" }),
  ).toHaveAttribute("aria-checked", "false");
  await page.getByLabel("删除 回归测试任务").click();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  await page.getByLabel("删除 回归测试任务").click();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "回归测试任务" }),
  ).toHaveCount(0);
});

test("信号分页和任务筛选，隐藏页面暂停轮询", async ({ page }) => {
  const { calls } = await fixtures(page);
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: /盯盘/ }).click();
  await expect(page.locator(".signal-block tbody tr")).toHaveCount(50);
  await page.locator(".signal-block").getByLabel("下一页").click();
  await expect(page.locator(".signal-block .pagination")).toContainText(
    "2 / 3",
  );
  await page.locator(".monitor-table tbody tr").first().click();
  await expect
    .poll(() =>
      calls.some(
        (c) => c.path.endsWith("/signals") && c.query.get("task_id") === "1",
      ),
    )
    .toBeTruthy();
  await page.getByRole("button", { name: /查看全部/ }).click();
  await page.getByRole("tab", { name: /行情/ }).click();
  const before = calls.filter((c) => c.path.endsWith("/tasks")).length;
  await page.clock.fastForward(30000);
  expect(calls.filter((c) => c.path.endsWith("/tasks")).length).toBe(before);
  await page.getByRole("tab", { name: /盯盘/ }).click();
  await expect
    .poll(() => calls.filter((c) => c.path.endsWith("/tasks")).length)
    .toBeGreaterThan(before);
});

test("桌面与手机无横向溢出，抽屉可键盘退出", async ({ page }) => {
  await fixtures(page);
  await page.goto("/");
  await selectMarket(page);
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      )
      .toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  await page.getByRole("tab", { name: /盯盘/ }).click();
  await page.getByRole("button", { name: "新建任务", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: "test-results/mobile-drawer.png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("延迟轮询不能覆盖刚完成的启停操作", async ({ page }) => {
  const state = await fixtures(page);
  await page.clock.install();
  await page.goto("/");
  await page.getByRole("tab", { name: /盯盘/ }).click();
  const toggle = page.getByRole("switch", { name: "启用 均线趋势观察" });
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  let release!: () => void;
  let pending = false;
  state.delayGet(async () => {
    pending = true;
    await new Promise<void>((resolve) => {
      release = resolve;
    });
  });
  await page.clock.fastForward(11000);
  await expect.poll(() => pending).toBeTruthy();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  release();
  await page.clock.fastForward(500);
  await expect(toggle).toHaveAttribute("aria-checked", "false");
});

test("正常动效可运行，手机标题保持两行，装饰图离线有替代", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fixtures(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await expect(page.locator("h1")).toHaveCSS("opacity", "1");
  await page.locator(".research-statement").scrollIntoViewIfNeeded();
  await expect
    .poll(() =>
      page
        .locator(".reveal-word")
        .first()
        .evaluate((el) => Number(getComputedStyle(el).opacity)),
    )
    .toBeGreaterThan(0.14);
  await page.locator(".landscape").scrollIntoViewIfNeeded();
  await expect(page.locator(".landscape-image")).toHaveAttribute(
    "src",
    "/landscape.svg",
  );
  await expect
    .poll(() =>
      page
        .locator(".landscape-image")
        .evaluate((el) => (el as HTMLImageElement).naturalWidth),
    )
    .toBeGreaterThan(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator("h1")
        .evaluate(
          (el) =>
            el.getBoundingClientRect().height /
            parseFloat(getComputedStyle(el).lineHeight),
        ),
    )
    .toBeLessThan(2.1);
  expect(errors).toEqual([]);
});
