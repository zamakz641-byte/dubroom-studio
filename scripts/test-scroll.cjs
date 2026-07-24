const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const outputDir = path.join(root, "output", "playwright", "scroll");
const windowSizes = [
  { width: 1120, height: 700, name: "minimum" },
  { width: 1366, height: 715, name: "laptop" },
  { width: 1480, height: 920, name: "default" },
];
const sections = ["dashboard", "projects", "studio", "library", "tools", "engines", "settings"];
const results = [];

fs.mkdirSync(outputDir, { recursive: true });

async function metric(locator) {
  return locator.evaluate((node) => ({
    top: node.scrollTop,
    height: node.clientHeight,
    scrollHeight: node.scrollHeight,
    max: Math.max(0, node.scrollHeight - node.clientHeight),
    overflowY: getComputedStyle(node).overflowY,
    className: node.className,
  }));
}

async function activeScroller(page) {
  return page.locator(".studio-viewport:visible, .page:visible, .onboarding-stage:visible").first();
}

async function routeTo(page, index) {
  await page.locator(".workspace-rail nav button").nth(index).click();
  const scroller = await activeScroller(page);
  await scroller.waitFor({ state: "visible", timeout: 5000 });
  let previous = -1;
  let stableSamples = 0;
  for (let attempt = 0; attempt < 20 && stableSamples < 3; attempt += 1) {
    const current = (await metric(scroller)).scrollHeight;
    stableSamples = current === previous ? stableSamples + 1 : 0;
    previous = current;
    await page.waitForTimeout(100);
  }
  return scroller;
}

async function wheelCase(page, scroller, deltaX, deltaY, label) {
  const before = await metric(scroller);
  await scroller.evaluate((node) => { node.scrollTop = 0; });
  const box = await scroller.boundingBox();
  if (!box) throw new Error(`${label}: scroller is not visible`);
  await page.mouse.move(
    box.x + Math.max(10, Math.min(box.width * 0.58, box.width - 10)),
    box.y + Math.max(10, Math.min(box.height * 0.55, box.height - 10)),
  );
  await page.mouse.wheel(deltaX, deltaY);
  await page.waitForTimeout(180);
  const after = await metric(scroller);
  const shouldMove = before.max > 2;
  const pass = shouldMove ? after.top > 0 : after.top <= 2;
  const result = { label, pass, shouldMove, input: { deltaX, deltaY }, before, after };
  results.push(result);
  if (!pass) throw new Error(`${label}: expected movement=${shouldMove}, scrollTop=${after.top}, max=${before.max}`);
}

async function keyboardCase(page, scroller, label) {
  const before = await metric(scroller);
  await scroller.evaluate((node) => { node.scrollTop = 0; });
  await page.locator("body").click({ position: { x: 4, y: 4 } }).catch(() => {});
  await page.keyboard.press("PageDown");
  await page.waitForTimeout(420);
  const after = await metric(scroller);
  const shouldMove = before.max > 2;
  const pass = shouldMove ? after.top > 0 : after.top <= 2;
  results.push({ label, pass, shouldMove, input: "PageDown", before, after });
  if (!pass) throw new Error(`${label}: PageDown left scrollTop=${after.top}, max=${before.max}`);
}

async function testWindow(size) {
  let app;
  let page;
  try {
    app = await electron.launch({ args: ["."], cwd: appDir, timeout: 30000 });
    page = await app.firstWindow();
    await app.evaluate(({ BrowserWindow }, dimensions) => {
      const win = BrowserWindow.getAllWindows()[0];
      win.setContentSize(dimensions.width, dimensions.height);
      win.center();
      win.focus();
    }, size);
    await page.waitForLoadState("domcontentloaded");
    await page.evaluate(() => {
      localStorage.setItem("dubroom.onboardingComplete", "true");
      localStorage.setItem("dubroom.onboardingResetVersion", "delivery-room-v3");
      localStorage.setItem("dubroom.locale", "fr");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector(".workspace-shell", { timeout: 15000 });
    await page.evaluate(() => {
      window.__scrollAudit = [];
      window.addEventListener("wheel", (event) => {
        const target = event.target instanceof Element ? event.target : null;
        window.__scrollAudit.push({
          x: event.deltaX,
          y: event.deltaY,
          mode: event.deltaMode,
          prevented: event.defaultPrevented,
          target: target ? `${target.tagName}.${target.className?.baseVal || target.className || ""}` : "unknown",
        });
      });
    });

    for (let index = 0; index < sections.length; index += 1) {
      const section = sections[index];
      const scroller = await routeTo(page, index);
      await wheelCase(page, scroller, 0, 520, `${size.name}/${section}/vertical`);
      await wheelCase(page, scroller, 420, 0, `${size.name}/${section}/horizontal-trackpad`);
      await wheelCase(page, scroller, 120, 360, `${size.name}/${section}/diagonal-trackpad`);
      await keyboardCase(page, scroller, `${size.name}/${section}/keyboard`);
    }

    const wheelAudit = await page.evaluate(() => window.__scrollAudit);
    results.push({
      label: `${size.name}/wheel-events-received`,
      pass: wheelAudit.length >= sections.length * 3,
      count: wheelAudit.length,
      sample: wheelAudit.slice(0, 8),
    });
  } catch (error) {
    if (page) {
      await page.screenshot({ path: path.join(outputDir, `failure-${size.name}.png`), fullPage: false }).catch(() => {});
    }
    throw error;
  } finally {
    if (app) await app.close().catch(() => {});
  }
}

(async () => {
  try {
    for (const size of windowSizes) await testWindow(size);
    const failed = results.filter((result) => !result.pass);
    if (failed.length) throw new Error(`${failed.length} scroll assertions failed`);
    console.log(JSON.stringify({ ok: true, assertions: results.length, results }, null, 2));
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: error.message, results }, null, 2));
    process.exitCode = 1;
  }
})();
