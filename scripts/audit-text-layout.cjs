const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const outputDir = path.join(root, "output", "playwright", "text-audit");
const sizes = [
  { name: "minimum", width: 1120, height: 700 },
  { name: "laptop", width: 1366, height: 715 },
];
const sections = ["dashboard", "projects", "studio", "library", "tools", "engines", "settings"];

fs.mkdirSync(outputDir, { recursive: true });

async function inspectText(page, label) {
  return page.evaluate((viewLabel) => {
    const issues = [];
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const viewport = { width: innerWidth, height: innerHeight };
    const mojibake = /(?:Ã.|Â.|â€|â€™|â€œ|â€|ï¿½|�)/;
    const translationKey = /^(?:activity|casting|common|dashboard|density|engines|export|library|models|nav|notifications|onboarding|performance|profile|projects|rvc|settings|shell|studio|subclean|theme|tools|voicebox|workflow)\.[\w.-]+$/i;
    let node;
    while ((node = walker.nextNode())) {
      const text = (node.nodeValue || "").replace(/\s+/g, " ").trim();
      if (!text) continue;
      const parent = node.parentElement;
      if (!parent) continue;
      const style = getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) < .08) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = range.getBoundingClientRect();
      if (rect.width < .5 || rect.height < .5) continue;
      const parentRect = parent.getBoundingClientRect();
      const inViewport = rect.bottom > 0 && rect.right > 0 && rect.top < viewport.height && rect.left < viewport.width;
      if (!inViewport) continue;
      const key = `${parent.tagName}|${parent.className}|${text}|${Math.round(rect.x)}|${Math.round(rect.y)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const base = {
        view: viewLabel,
        tag: parent.tagName,
        className: String(parent.className || "").slice(0, 120),
        ancestry: Array.from(parent.closest(".page,.studio-workbench,.onboarding-shell") ? [parent] : []).length === 0 ? "" : (() => {
          const parts = [];
          let current = parent;
          for (let depth = 0; current && depth < 5; depth += 1, current = current.parentElement) {
            const name = current.tagName.toLowerCase();
            const classes = typeof current.className === "string" && current.className.trim()
              ? `.${current.className.trim().split(/\s+/).slice(0, 3).join(".")}`
              : "";
            parts.push(`${name}${classes}`);
          }
          return parts.join(" < ");
        })(),
        text: text.slice(0, 140),
        fontSize: Number.parseFloat(style.fontSize),
        lineHeight: style.lineHeight,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      };
      if (base.fontSize < 9.9) issues.push({ type: "tiny", ...base });
      if (mojibake.test(text)) issues.push({ type: "encoding", ...base });
      if (translationKey.test(text)) issues.push({ type: "translation-key", ...base });

      const clipsX = ["hidden", "clip"].includes(style.overflowX) &&
        (rect.left < parentRect.left - 1 || rect.right > parentRect.right + 1);
      const clipsY = ["hidden", "clip"].includes(style.overflowY) &&
        (rect.top < parentRect.top - 1 || rect.bottom > parentRect.bottom + 1);
      const deliberateTruncation = parent.matches('.truncate, [class*="line-clamp-"]');
      if ((clipsX || clipsY) && !deliberateTruncation) {
        issues.push({ type: clipsX ? "clipped-x" : "clipped-y", ...base });
      }
    }
    return {
      label: viewLabel,
      viewport,
      documentOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      issues,
    };
  }, label);
}

async function setSize(app, size) {
  await app.evaluate(({ BrowserWindow }, target) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.setContentSize(target.width, target.height);
    win.center();
  }, size);
}

async function inspectView(page, label) {
  const collected = [await inspectText(page, label)];
    const scroller = page
      .locator('[data-testid="onboarding-stage"]:visible, [data-testid="app-content"] .overflow-auto:visible, [data-testid="app-content"] .overflow-y-auto:visible')
      .first();
  if (await scroller.count()) {
    const maximum = await scroller.evaluate(node => Math.max(0, node.scrollHeight - node.clientHeight));
    if (maximum > 8) {
      await scroller.evaluate((node, top) => { node.scrollTop = top; }, maximum);
      await page.waitForTimeout(80);
      collected.push(await inspectText(page, `${label}/bottom`));
      await scroller.evaluate(node => { node.scrollTop = 0; });
    }
  }
  return collected;
}

(async () => {
  let app;
  const results = [];
  try {
    app = await electron.launch({ args: ["."], cwd: appDir, timeout: 30000 });
    const page = await app.firstWindow();
    await page.waitForLoadState("domcontentloaded");
    await page.evaluate(() => {
      localStorage.setItem("dubroom.onboardingComplete", "true");
      localStorage.setItem("dubroom.onboardingResetVersion", "tailwind-v2-release");
      localStorage.setItem("dubroom.locale", "fr");
      localStorage.setItem("dubroom.density", "comfortable");
      localStorage.setItem("dubroom.theme", "amber");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="app-shell"]', { timeout: 15000 });

    for (const size of sizes) {
      await setSize(app, size);
      await page.waitForTimeout(350);
      for (let index = 0; index < sections.length; index += 1) {
        await page.locator('[data-testid="primary-navigation"] > button').nth(index).click();
        await page.waitForTimeout(260);
        const section = sections[index];
        results.push(...await inspectView(page, `${size.name}/${section}`));
        await page.screenshot({ path: path.join(outputDir, `${size.name}-${section}.png`) });

        if (section === "studio" && await page.locator('[data-testid="studio-workbench"]').count()) {
          const domains = page.locator('[data-testid="studio-modes"] > button');
          for (let domainIndex = 0; domainIndex < await domains.count(); domainIndex += 1) {
            await domains.nth(domainIndex).click();
            await page.waitForTimeout(180);
            results.push(...await inspectView(page, `${size.name}/studio-mode-${domainIndex + 1}`));
          }
        }
        if (section === "library") {
          const tabs = page.locator('[data-testid="library-tabs"] > button');
          for (let tabIndex = 0; tabIndex < await tabs.count(); tabIndex += 1) {
            await tabs.nth(tabIndex).click();
            await page.waitForTimeout(120);
            results.push(...await inspectView(page, `${size.name}/library-tab-${tabIndex + 1}`));
          }
        }
        if (section === "tools") {
          const tools = page.locator('[data-testid="tools-tabs"] > button');
          for (let toolIndex = 0; toolIndex < await tools.count(); toolIndex += 1) {
            await tools.nth(toolIndex).click();
            await page.waitForTimeout(120);
            results.push(...await inspectView(page, `${size.name}/tools-${toolIndex + 1}`));
          }
        }
        if (section === "engines") {
          const categories = page.locator('[data-testid="engine-tabs"] > button');
          for (let categoryIndex = 0; categoryIndex < await categories.count(); categoryIndex += 1) {
            await categories.nth(categoryIndex).click();
            await page.waitForTimeout(140);
            results.push(...await inspectView(page, `${size.name}/engines-category-${categoryIndex + 1}`));
          }
        }
        if (section === "settings") {
          const settings = page.locator('[data-testid="settings-tabs"] > button');
          for (let settingIndex = 0; settingIndex < await settings.count(); settingIndex += 1) {
            await settings.nth(settingIndex).click();
            await page.waitForTimeout(100);
            results.push(...await inspectView(page, `${size.name}/settings-${settingIndex + 1}`));
          }
        }
      }
    }

    for (const size of sizes) {
      await setSize(app, size);
      await page.evaluate(() => {
        localStorage.removeItem("dubroom.onboardingComplete");
        localStorage.removeItem("dubroom.onboardingResetVersion");
      });
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector('[data-testid="onboarding"]', { timeout: 10000 });
      for (let stepIndex = 0; stepIndex < 8; stepIndex += 1) {
        results.push(...await inspectView(page, `${size.name}/onboarding-${stepIndex + 1}`));
        await page.screenshot({ path: path.join(outputDir, `${size.name}-onboarding-${stepIndex + 1}.png`) });
        if (stepIndex < 7) {
          await page.getByTestId("onboarding-next").click();
          await page.waitForTimeout(180);
        }
      }
    }

    const flat = results.flatMap(result => result.issues);
    const summary = flat.reduce((map, issue) => {
      map[issue.type] = (map[issue.type] || 0) + 1;
      return map;
    }, {});
    const report = { ok: !summary.encoding && !summary["translation-key"], summary, views: results };
    fs.writeFileSync(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ok: report.ok, summary, samples: flat.slice(0, 80) }, null, 2));
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    if (app) await app.close().catch(() => {});
  }
})();
