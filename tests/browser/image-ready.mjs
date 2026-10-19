/** 图片截图定向回归：真实静态资源与延迟/404夹具，不启动或声称验证商城交易。 */
import { chromium, expect } from "../../build/wsl/browser/node_modules/@playwright/test/index.mjs";
import { readyForScreenshot } from "./screenshot-ready.mjs";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../../", import.meta.url));
const assets = ["sports-hero-v1.webp", "shoe-run-v1.webp", "shoe-court-v1.webp", "shoe-street-v1.webp"];
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://localhost");
  if (url.pathname === "/") {
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(`<!doctype html><html lang="zh"><meta charset="utf-8"><title>图片就绪夹具</title>
      <style>img{display:block;width:280px;height:280px;object-fit:contain;margin-bottom:300px}</style>
      ${Array.from({ length: 9 }, (_, i) => `<img alt="fixture-${i}" loading="lazy" src="/assets/${assets[i % assets.length]}?delay=${i}">`).join("")}</html>`);
    return;
  }
  const name = path.basename(url.pathname);
  if (url.pathname.startsWith("/assets/") && assets.includes(name)) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    response.setHeader("Content-Type", "image/webp");
    response.end(await readFile(path.join(root, "src/web/public/assets", name)));
    return;
  }
  response.writeHead(404).end();
});
const report = { platform: process.platform, scope: "static image fixtures, not real business integration", checks: [] };
let browser;
try {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  browser = await chromium.launch();
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await readyForScreenshot(page);
    const images = await page.locator("img").evaluateAll((nodes) => nodes.map((image) => ({
      complete: image.complete, width: image.naturalWidth, height: image.naturalHeight,
    })));
    expect(images).toHaveLength(9);
    expect(images.every((image) => image.complete && image.width > 0 && image.height > 0)).toBe(true);
    report.checks.push({ name: `lazy-and-delayed-images-${width}`, images: images.length, passed: true });
    await page.close();
  }
  const broken = await browser.newPage();
  await broken.goto(`http://127.0.0.1:${server.address().port}/`);
  await broken.locator("img").first().evaluate((image) => { image.src = "/missing-image.webp"; });
  let rejected = false;
  try { await readyForScreenshot(broken); } catch (error) {
    if (error.name !== "TimeoutError") throw error;
    rejected = true;
  }
  expect(rejected).toBe(true);
  report.checks.push({ name: "broken-image-rejects-capture", passed: true });
  await broken.close();
  const readme = await readFile(path.join(root, "README.md"), "utf8");
  expect(readme).toContain("(tests/reports/wsl/sports-ui/desktop-home.png)");
  const screenshot = await readFile(path.join(root, "tests/reports/wsl/sports-ui/desktop-home.png"));
  expect(screenshot.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))).toBe(true);
  report.checks.push({ name: "readme-references-existing-png", passed: true });
  report.passed = true;
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
  await mkdir(path.join(root, "tests/reports/wsl"), { recursive: true });
  await writeFile(path.join(root, "tests/reports/wsl/t056-image-ready.json"), JSON.stringify(report, null, 2) + "\n");
}
console.log(JSON.stringify(report));
