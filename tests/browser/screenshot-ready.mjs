/**
 * 等待全页图片可解码、字体就绪并完成绘制，再允许发布截图。
 * @param {import('@playwright/test').Page} page 已确认业务内容出现的页面。
 */
export async function readyForScreenshot(page) {
  // 全页截图包含视口外的懒加载商品，必须先触发加载，不能把灰色占位当作成功。
  await page.locator("img").evaluateAll((images) => {
    for (const image of images) image.loading = "eager";
  });
  await page.waitForFunction(
    () => [...document.images].every((image) => image.complete && image.naturalWidth > 0),
    undefined,
    { timeout: 15000 },
  );
  await page.evaluate(async () => {
    await Promise.all([...document.images].map((image) => image.decode()));
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}
