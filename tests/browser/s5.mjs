import {
  chromium,
  expect,
} from "../../build/wsl/browser/node_modules/@playwright/test/index.mjs";
import AxeBuilder from "../../build/wsl/browser/node_modules/@axe-core/playwright/dist/index.mjs";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
const config = JSON.parse(await readFile(process.env.S5_CONFIG, "utf8"));
const report = "tests/reports/wsl/sports-ui";
await mkdir(report, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: "zh-CN",
  reducedMotion: "reduce",
});
const page = await context.newPage();
const failures = [],
  checks = [];
const started = Date.now();
page.on("pageerror", (e) => failures.push(e.message));
const check = async (name, fn) => {
  await fn();
  checks.push({ name, status: "PASS" });
  console.log("PASS", name);
};
function fixture(...args) {
  execFileSync(
    "build/wsl/venv/bin/python",
    ["tests/browser/fixture.py", ...args],
    { env: process.env },
  );
}
async function navigate(hash) {
  await page.goto(config.baseUrl + "/#" + hash);
  await page.locator(".header").waitFor();
}
async function a11y() {
  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    scan.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
}
async function noOverflow() {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}
await page.route("**/api/seckill/captcha?*", async (route) => {
  const response = await route.fetch();
  if (response.status() === 200) {
    const data = await response.json(),
      url = new URL(route.request().url());
    fixture(
      "answer",
      url.searchParams.get("activityId"),
      url.searchParams.get("skuId"),
      data.captchaId,
    );
  }
  await route.fulfill({ response });
});
async function registerUser(name) {
  await page.getByRole("button", { name: "登录 / 注册" }).click();
  await page.getByRole("button", { name: "第一次来？创建账号" }).click();
  await page.getByLabel("用户名", { exact: true }).fill(name);
  await page.getByLabel("密码", { exact: true }).fill(config.password);
  await page.getByRole("button", { name: "创建并登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "退出账号" })).toBeVisible();
}
async function purchase(item) {
  await navigate(`/product/${item.goodsId}`);
  await page
    .getByRole("button", { name: "尺码 " + item.sizeEu, exact: true })
    .click();
  await expect(page.getByRole("button", { name: "立即抢购" })).toBeEnabled();
  await page.getByRole("button", { name: "立即抢购" }).click();
  await expect(page.getByRole("img", { name: "6 位数字验证码" })).toBeVisible();
  await page.getByLabel("验证码", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "验证并抢购" }).dblclick();
  await expect(
    page.getByRole("heading", { name: "待支付", exact: true }),
  ).toBeVisible({ timeout: 120000 });
  return page.url().split("/order/")[1];
}
try {
  await check(
    "desktop real catalog, original assets, accessibility",
    async () => {
      await navigate("/");
      await expect(page.locator(".product-card")).toHaveCount(8);
      await page.locator(".product-card img").first().waitFor();
      await page.evaluate(async () => {
        await Promise.all(
          [...document.images].map((i) => i.decode().catch(() => {})),
        );
      });
      expect(
        await page
          .locator("img")
          .evaluateAll((imgs) =>
            imgs.every((i) => i.complete && i.naturalWidth > 0),
          ),
      ).toBe(true);
      await noOverflow();
      await a11y();
      await page.screenshot({
        path: report + "/desktop-home.png",
        fullPage: true,
      });
    },
  );
  await check("catalog search, empty results and price sort", async () => {
    await navigate("/catalog");
    await page.getByLabel("寻找好物").fill("不存在");
    await expect(
      page.getByText("暂无符合条件的好物，试试其他关键词。"),
    ).toBeVisible();
    await page.getByLabel("寻找好物").fill("");
    await page.getByLabel("排列方式").selectOption("low");
    await expect(page.locator(".product-card h3").first()).toHaveText(
      "STREET/03 · 城市休闲鞋",
    );
    await a11y();
  });
  await check("register/login modal and keyboard focus", async () => {
    await registerUser("browser_" + Date.now());
    await page.getByRole("button", { name: "退出账号" }).click();
    await page.getByRole("button", { name: "登录 / 注册" }).click();
    await expect(page.getByLabel("用户名", { exact: true })).toBeFocused();
    await a11y();
    await page.keyboard.press("Escape");
    await expect(page.locator("dialog.dialog")).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "登录 / 注册" }),
    ).toBeFocused();
    await registerUser("purchase_" + Date.now());
  });
  let first;
  await check(
    "size selection, gallery, persisted bag and cart boundary",
    async () => {
      await navigate(`/product/${config.items[0].goodsId}`);
      await expect(
        page.getByRole("button", { name: "选择尺码后抢购" }),
      ).toBeDisabled();
      await expect(
        page.getByRole("button", { name: "尺码 40", exact: true }),
      ).toBeDisabled();
      await page.getByRole("button", { name: "尺码 42", exact: true }).click();
      await page.getByRole("button", { name: "查看鞋面细节" }).click();
      await expect(page.locator(".detail-image img")).toHaveClass(/zoom/);
      await page.getByRole("button", { name: "加入抢购清单" }).click();
      await expect(page.locator(".bag-drawer")).toBeVisible();
      await a11y();
      await page.getByRole("link", { name: "查看清单与抢购流程" }).click();
      await expect(page.locator(".cart-row")).toHaveCount(1);
      await noOverflow();
      await a11y();
      await page.reload();
      await expect(page.locator(".cart-row")).toHaveCount(1);
      await page.screenshot({
        path: report + "/desktop-cart.png",
        fullPage: true,
      });
    },
  );
  await check(
    "wrong captcha, refresh and stable request identity",
    async () => {
      await navigate(`/product/${config.items[0].goodsId}`);
      await page.getByRole("button", { name: "尺码 42", exact: true }).click();
      await page.getByRole("button", { name: "立即抢购" }).click();
      await expect(
        page.getByRole("img", { name: "6 位数字验证码" }),
      ).toBeVisible();
      const identity = await page.evaluate(
        () =>
          JSON.parse(
            localStorage.getItem(
              "shijian.attempts." +
                JSON.parse(sessionStorage.getItem("shijian.session")).userId,
            ),
          )[0].requestId,
      );
      await page.getByLabel("验证码", { exact: true }).fill("000000");
      await page.getByRole("button", { name: "验证并抢购" }).click();
      await expect(page.locator("dialog [role=alert]")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "验证并抢购" }),
      ).toBeDisabled();
      await page.getByRole("button", { name: "换一张" }).click();
      await expect(
        page.getByRole("img", { name: "6 位数字验证码" }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () =>
            JSON.parse(
              localStorage.getItem(
                "shijian.attempts." +
                  JSON.parse(sessionStorage.getItem("shijian.session")).userId,
              ),
            )[0].requestId,
        ),
      ).toBe(identity);
      await page.keyboard.press("Escape");
    },
  );
  await check(
    "real captcha -> C++ -> RocketMQ -> MySQL order, stable request on lost response",
    async () => {
      let buys = 0;
      await page.route("**/api/seckill/buy", async (route) => {
        buys++;
        const response = await route.fetch();
        expect(response.status()).toBe(202);
        await route.abort("failed");
      });
      first = await purchase(config.items[0]);
      expect(buys).toBe(1);
      await page.unroute("**/api/seckill/buy");
      expect(
        await page.evaluate(
          () =>
            JSON.parse(
              localStorage.getItem(
                "shijian.attempts." +
                  JSON.parse(sessionStorage.getItem("shijian.session")).userId,
              ),
            )[0].submitted,
        ),
      ).toBe(true);
      await page.reload();
      await expect(
        page.getByRole("heading", { name: "待支付", exact: true }),
      ).toBeVisible();
      await a11y();
      await page.screenshot({
        path: report + "/desktop-order.png",
        fullPage: true,
      });
    },
  );
  await check(
    "mock payment, duplicate-click guard and authoritative paid state",
    async () => {
      let payments = 0;
      page.on("request", (r) => {
        if (r.url().endsWith("/api/order/pay")) payments++;
      });
      await page.getByRole("button", { name: /^模拟支付/ }).dblclick();
      await expect(
        page.getByRole("heading", { name: "已支付", exact: true }),
      ).toBeVisible();
      expect(payments).toBe(1);
      await page.reload();
      await expect(
        page.getByRole("heading", { name: "已支付", exact: true }),
      ).toBeVisible();
      await navigate("/orders");
      await expect(page.locator(".order-row")).toHaveCount(1);
      await expect(page.locator(".order-row .pill")).toHaveText("已支付");
      await a11y();
    },
  );
  await check(
    "second real order, expiry close and no payment action",
    async () => {
      const second = await purchase(config.items[1]);
      fixture("expire", second);
      await expect(
        page.getByRole("heading", { name: "已关闭", exact: true }),
      ).toBeVisible({ timeout: 20000 });
      await expect(page.getByRole("button", { name: /^模拟支付/ })).toHaveCount(
        0,
      );
    },
  );
  await check(
    "sold-out display disables buy (private cache fixture, restored)",
    async () => {
      const item = config.items[2];
      fixture("stock", item.activityId, item.skuId, "0");
      try {
        await navigate(`/product/${item.goodsId}`);
        await expect(
          page.getByRole("button", { name: "本场已售罄" }),
        ).toBeDisabled();
      } finally {
        fixture("stock", item.activityId, item.skuId, "10");
      }
    },
  );
  await check(
    "compensating and failed request UI (explicit response fixture)",
    async () => {
      const request = await page.evaluate(
        () =>
          JSON.parse(
            localStorage.getItem(
              "shijian.attempts." +
                JSON.parse(sessionStorage.getItem("shijian.session")).userId,
            ),
          )[0],
      );
      let state = "COMPENSATING";
      await page.route("**/api/order/status?activityId=*", (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            requestId: request.requestId,
            requestState: state,
            orderId: null,
            orderState: null,
            amountFen: null,
            failureCode: state === "FAILED" ? "REQUEST_RECOVERY_TIMEOUT" : null,
          }),
        }),
      );
      try {
        await navigate(`/request/${request.requestId}`);
        await expect(
          page.getByRole("heading", { name: "正在恢复处理", exact: true }),
        ).toBeVisible();
        await expect(
          page.getByRole("button", { name: /^模拟支付/ }),
        ).toHaveCount(0);
        state = "FAILED";
        await expect(
          page.getByRole("heading", { name: "抢购未成功", exact: true }),
        ).toBeVisible({ timeout: 10000 });
        await expect(
          page.getByText(
            "本次请求未生成订单，库存恢复由服务端处理。请返回鞋款页面查看其他活动。",
          ),
        ).toBeVisible();
        await a11y();
      } finally {
        await page.unroute("**/api/order/status?activityId=*");
      }
    },
  );
  await check(
    "mobile real detail and homepage: layout, accessibility, images",
    async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await navigate(`/product/${config.items[0].goodsId}`);
      await page.getByRole("button", { name: "尺码 42", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "立即抢购" }),
      ).toBeVisible();
      await noOverflow();
      await a11y();
      await page.screenshot({
        path: report + "/mobile-detail.png",
        fullPage: true,
      });
      await navigate("/");
      await expect(page.locator(".product-card")).toHaveCount(8);
      await noOverflow();
      await a11y();
      await page.screenshot({
        path: report + "/mobile-home.png",
        fullPage: true,
      });
      await navigate("/orders");
      await noOverflow();
      await page.screenshot({
        path: report + "/mobile-orders.png",
        fullPage: true,
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
    },
  );
  await check("USER frontend guard and backend forbidden", async () => {
    await check('sport filters, flash sessions and responsive breakpoints',async()=>{
      await navigate('/catalog/篮球');await expect(page.locator('.product-card')).toHaveCount(1);
      await page.getByLabel('价格范围').selectOption('500');await expect(page.locator('.product-card')).toHaveCount(0);
      await page.getByRole('button',{name:'清除筛选'}).click();await expect(page.locator('.product-card')).toHaveCount(4);
      await navigate('/flash');await expect(page.locator('.flash-grid .product-card')).toHaveCount(4);await a11y();
      await page.getByRole('button',{name:'即将开抢',exact:true}).click();await expect(page.getByText('此场次暂时没有鞋款。')).toBeVisible();
      await page.getByRole('button',{name:'已开启',exact:true}).click();await expect(page.locator('.flash-grid .product-card')).toHaveCount(4);
      await page.screenshot({path:report+'/desktop-flash.png',fullPage:true});
      for(const width of [390,640,768,1024,1280,1440]){await page.setViewportSize({width,height:900});await navigate('/');await noOverflow();await page.screenshot({path:report+'/home-'+width+'.png',fullPage:true});await navigate('/catalog');await noOverflow()}
      await page.setViewportSize({width:1440,height:1000});
    });
    await navigate("/admin");
    await expect(
      page.getByRole("heading", { name: "需要管理员账号" }),
    ).toBeVisible();
    expect(
      await page.evaluate(async () => {
        const s = JSON.parse(sessionStorage.getItem("shijian.session"));
        return (
          await fetch("/api/admin/users", {
            headers: { Authorization: "Bearer " + s.token },
          })
        ).status;
      }),
    ).toBe(403);
    expect(
      await page.evaluate(async () => {
        const s = JSON.parse(sessionStorage.getItem("shijian.session"));
        return (
          await fetch("/api/admin/skus/1", {
            method: "PATCH",
            headers: {
              Authorization: "Bearer " + s.token,
              "Content-Type": "application/json",
            },
            body: "{}",
          })
        ).status;
      }),
    ).toBe(403);
    expect(
      await page.evaluate(async () => {
        const s = JSON.parse(sessionStorage.getItem("shijian.session"));
        return (
          await fetch("/api/admin/goods", {
            headers: { Authorization: "Bearer " + s.token },
          })
        ).status;
      }),
    ).toBe(403);
  });
  await check(
    "ADMIN goods create/edit, activity create/activate/end, users, orders, recovery",
    async () => {
      await page.getByRole("button", { name: "退出账号" }).click();
      await page.getByRole("button", { name: "登录 / 注册" }).click();
      await page.getByLabel("用户名", { exact: true }).fill("admin");
      await page.getByLabel("密码", { exact: true }).fill(config.password);
      await page.getByRole("button", { name: "登录", exact: true }).click();
      await page.getByRole("link", { name: "管理", exact: true }).click();
      await page.getByLabel("商品名称").fill("后台创建的训练鞋");
      await page.getByLabel("商品说明").fill("浏览器真实管理测试。");
      await page.getByLabel("价格（分）", { exact: true }).fill("13900");
      await page.getByLabel("总库存").fill("12");
      await page.getByRole("button", { name: "创建商品", exact: true }).click();
      await expect(
        page.locator("table").getByText("后台创建的训练鞋"),
      ).toBeVisible();
      const createdSku = await page
        .locator("tr")
        .filter({ hasText: "后台创建的训练鞋" })
        .locator("td")
        .nth(1)
        .innerText();
      await page.getByText("维护鞋款尺码与运动属性", { exact: true }).click();
      await page.getByLabel("属性 SKU").selectOption(createdSku);
      await page.getByLabel("EU 尺码").fill("40");
      await page.getByLabel("运动类别").selectOption("训练");
      await page.getByLabel("配色", { exact: true }).fill("黑白");
      await page.getByRole("button", { name: "保存鞋款属性" }).click();
      await page
        .locator("tr")
        .filter({ hasText: "后台创建的训练鞋" })
        .getByRole("button", { name: "编辑 / 下架" })
        .click();
      await page.getByLabel("商品说明").fill("编辑保存成功。");
      await page.getByLabel("在商城展示").uncheck();
      await page.getByRole("button", { name: "保存商品" }).click();
      await expect(
        page
          .locator("tr")
          .filter({ hasText: "后台创建的训练鞋" })
          .getByText("已下架", { exact: true }),
      ).toBeVisible();
      await page
        .locator("tr")
        .filter({ hasText: "后台创建的训练鞋" })
        .getByRole("button", { name: "编辑 / 下架" })
        .click();
      await page.getByLabel("在商城展示").check();
      await page.getByRole("button", { name: "保存商品" }).click();
      await expect(
        page
          .locator("tr")
          .filter({ hasText: "后台创建的训练鞋" })
          .getByText("在售", { exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "活动", exact: true }).click();
      await page.getByLabel("活动名称").fill("浏览器新活动");
      const goodsOption = page
        .getByLabel("商品 SKU")
        .locator("option")
        .filter({ hasText: "后台创建的训练鞋" });
      await page
        .getByLabel("商品 SKU")
        .selectOption(await goodsOption.getAttribute("value"));
      await page.getByLabel("活动库存").fill("5");
      await page.getByLabel("活动价（分）").fill("11900");
      const fmt = (d) => {
        const x = new Date(d);
        return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}T${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`;
      };
      await page.getByLabel("开始时间").fill(fmt(Date.now() - 60000));
      await page.getByLabel("结束时间").fill(fmt(Date.now() + 3600000));
      await page.getByRole("button", { name: "创建活动", exact: true }).click();
      let row = page.locator("tr").filter({ hasText: "浏览器新活动" });
      await row.getByRole("button", { name: "开启活动" }).click();
      await expect(row.getByText("已开启", { exact: true })).toBeVisible();
      expect(
        await page.evaluate(async (sku) => {
          const s = JSON.parse(sessionStorage.getItem("shijian.session"));
          return (
            await fetch("/api/admin/skus/" + sku, {
              method: "PATCH",
              headers: {
                Authorization: "Bearer " + s.token,
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                sizeEu: "42",
                category: "训练",
                colorway: "黑白",
              }),
            })
          ).status;
        }, createdSku),
      ).toBe(409);
      await row.getByRole("button", { name: "结束活动" }).click();
      await expect(row.getByText("已结束", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "用户", exact: true }).click();
      await expect(page.locator("table tbody tr")).toHaveCount(3);
      const userRow = page.locator("tr").filter({ hasText: "browser_" });
      await userRow.getByRole("button", { name: "禁用", exact: true }).click();
      await expect(
        userRow.getByRole("button", { name: "启用", exact: true }),
      ).toBeVisible();
      await userRow.getByRole("button", { name: "启用", exact: true }).click();
      await page.getByRole("button", { name: "订单", exact: true }).click();
      await expect(page.locator("table tbody tr")).toHaveCount(2);
      await page.getByRole("button", { name: "恢复处理", exact: true }).click();
      await page.getByRole("button", { name: "执行一轮恢复" }).click();
      await expect(page.getByText("暂无记录。")).toBeVisible();
      await expect(
        page
          .locator(".metric-grid > div")
          .filter({ hasText: "终止失败" })
          .locator("strong"),
      ).toHaveText("0");
      await a11y();
      await page.screenshot({
        path: report + "/desktop-admin.png",
        fullPage: true,
      });
    },
  );
  await check(
    "API outage displays actionable error instead of fake catalog",
    async () => {
      await page.route("**/api/goods", (r) =>
        r.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            code: "DEPENDENCY_UNAVAILABLE",
            message: "服务暂不可用，请稍后重试。",
          }),
        }),
      );
      await navigate("/catalog");
      await page.reload();
      await expect(page.getByRole("alert")).toBeVisible();
      await expect(page.locator(".product-card")).toHaveCount(0);
      await page.unroute("**/api/goods");
      await page.getByRole("button", { name: "重新加载" }).click();
      await expect(page.locator(".product-card")).toHaveCount(5);
    },
  );
  await check("no browser JavaScript exceptions", async () =>
    expect(failures).toEqual([]),
  );
} catch (e) {
  await page.screenshot({ path: report + "/failure.png", fullPage: true });
  checks.push({ name: "execution failure", status: "FAIL", error: e.stack });
  throw e;
} finally {
  await writeFile(
    report + "/results.json",
    JSON.stringify(
      {
        date: new Date().toISOString(),
        runtime: process.platform,
        node: process.version,
        browser: browser.version(),
        elapsedSeconds: (Date.now() - started) / 1000,
        checks,
        fixtures:
          "captcha answer fixed privately in owned Redis; expiry/SOLD_OUT controlled privately; lost response injected after real accepted HTTP response; COMPENSATING/FAILED UI responses and goods 503 are explicitly injected, not claimed as real backend failures",
      },
      null,
      2,
    ),
  );
  await browser.close();
}
