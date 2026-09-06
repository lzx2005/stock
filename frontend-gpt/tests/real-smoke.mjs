import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
await mkdir("test-results", { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Real data smoke stays read-only: prevent UI automatic refresh from warming real caches.
await page.route("**/api/klines?**", async (route) => {
  const url = new URL(route.request().url());
  url.searchParams.delete("refresh");
  await route.continue({ url: url.toString() });
});
await page.goto("http://127.0.0.1:5178/");
await page.locator(".instrument").first().waitFor({ timeout: 60000 });
const count = await page.locator(".panel-head h3").innerText();
await page.locator(".instrument").first().click();
await page.getByRole("img", { name: /根/ }).waitFor({ timeout: 60000 });
const chart = await page
  .getByRole("img", { name: /根/ })
  .getAttribute("aria-label");
await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: "test-results/real-desktop.png" });
await page
  .locator(".market-grid")
  .screenshot({ path: "test-results/real-market.png" });
await page.getByRole("tab", { name: /因子/ }).click();
await page.locator(".factor-block tbody tr").first().waitFor();
const factorCount = await page.locator(".factor-block tbody tr").count();
await page
  .locator(".factor-page")
  .screenshot({ path: "test-results/real-factors.png" });
await page.getByRole("tab", { name: /盯盘/ }).click();
await page.locator(".monitor-table .busy").waitFor({ state: "hidden" });
const taskCount = await page.locator(".monitor-table tbody tr").count();
await page
  .locator(".monitor-page")
  .screenshot({ path: "test-results/real-monitor.png" });
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("tab", { name: /行情/ }).click();
await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: "test-results/real-mobile.png" });
console.log(
  JSON.stringify({
    coverage: count,
    chart,
    factorCount,
    taskCount,
    horizontalOverflow: await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    errors,
  }),
);
await browser.close();
if (errors.length) process.exitCode = 1;
