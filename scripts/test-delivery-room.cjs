const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const outputDir = path.join(root, "output", "playwright", "delivery-room-v2");
const sizes = [
  { name: "minimum", width: 1120, height: 700 },
  { name: "laptop", width: 1366, height: 715 },
  { name: "default", width: 1480, height: 920 },
  { name: "fullhd", width: 1920, height: 1080 },
];
fs.mkdirSync(outputDir, { recursive: true });

async function firstProjectId() {
  const response = await fetch("http://127.0.0.1:8766/projects");
  if (!response.ok) throw new Error(`Projects API returned ${response.status}`);
  const payload = await response.json();
  const projects = Array.isArray(payload) ? payload : payload.projects;
  if (!projects?.length)
    throw new Error("No project is available for the Studio V2 test");
  return projects[0].id;
}

(async () => {
  let app;
  const assertions = [];
  const screenshots = [];
  try {
    app = await electron.launch({ args: ["."], cwd: appDir, timeout: 30000 });
    const page = await app.firstWindow();
    await page.waitForLoadState("domcontentloaded");
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        const response = await fetch("http://127.0.0.1:8766/health");
        if (response.ok) break;
      } catch (error) {
        if (attempt === 39) throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const projectId = await firstProjectId();
    await page.evaluate((activeProjectId) => {
      localStorage.setItem("dubroom.onboardingComplete", "true");
      localStorage.setItem(
        "dubroom.onboardingResetVersion",
        "tailwind-v2-release",
      );
      localStorage.setItem("dubroom.locale", "fr");
      localStorage.setItem("dubroom.activeProjectId", activeProjectId);
    }, projectId);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("app-shell").waitFor({ timeout: 15000 });
    assertions.push("Tailwind V2 shell loaded");

    const performanceProfile = await page
      .locator("html")
      .getAttribute("data-performance");
    if (!["fluid", "balanced", "economy"].includes(performanceProfile)) {
      throw new Error(
        `Invalid adaptive performance profile: ${performanceProfile}`,
      );
    }
    assertions.push(`Adaptive performance profile: ${performanceProfile}`);

    await page.getByRole("button", { name: "Studio", exact: true }).click();
    const studio = page.getByTestId("studio-workbench");
    await studio.waitFor({ timeout: 20000 });
    const timeline = page.getByTestId("studio-timeline");
    await timeline.waitFor({ timeout: 10000 });
    assertions.push("Persistent timeline loaded");

    const videoFit = await page
      .locator("video")
      .first()
      .evaluate((node) => getComputedStyle(node).objectFit)
      .catch(() => "no-video");
    if (!["contain", "no-video"].includes(videoFit))
      throw new Error(`Video uses ${videoFit} instead of contain`);
    assertions.push(`Video fit: ${videoFit}`);

    const scroller = page.getByTestId("timeline-scroll");
    await scroller.evaluate((node) => {
      node.scrollLeft = 0;
      node.dataset.wheelAudit = "waiting";
      node.addEventListener(
        "wheel",
        (event) => {
          node.dataset.wheelAudit = `${event.deltaX}|${event.deltaY}|prevented:${event.defaultPrevented}|ctrl:${event.ctrlKey}|meta:${event.metaKey}|shift:${event.shiftKey}`;
        },
        { once: true },
      );
    });
    const beforeScroll = await scroller.evaluate((node) => ({
      left: node.scrollLeft,
      width: node.clientWidth,
      scrollWidth: node.scrollWidth,
      max: node.scrollWidth - node.clientWidth,
    }));
    await page.waitForTimeout(500);
    const scrollBox = await scroller.boundingBox();
    if (!scrollBox) throw new Error("Timeline scroller is not visible");
    await page.mouse.move(
      scrollBox.x + scrollBox.width * 0.65,
      scrollBox.y + scrollBox.height * 0.5,
    );
    await page.mouse.wheel(420, 0);
    await page.waitForTimeout(250);
    const timelineScrollLeft = await scroller.evaluate(
      (node) => node.scrollLeft,
    );
    const wheelAudit = await scroller.getAttribute("data-wheel-audit");
    const scrollDebug = await scroller.getAttribute("data-scroll-debug");
    if (timelineScrollLeft <= 0)
      throw new Error(
        `Horizontal two-finger timeline scroll did not move: before=${JSON.stringify(beforeScroll)}, event=${wheelAudit}, handler=${scrollDebug}`,
      );
    assertions.push(`Horizontal trackpad scroll: ${timelineScrollLeft}px`);

    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].setContentSize(1480, 920);
    });
    await page.waitForTimeout(300);
    const studioTarget = path.join(outputDir, "studio-media-default.png");
    await page.screenshot({ path: studioTarget });
    screenshots.push(studioTarget);

    await page.getByTestId("studio-modes").getByRole("button").last().click();
    const exportInspector = page.getByTestId("export-inspector");
    await exportInspector.waitFor({ timeout: 10000 });
    await page
      .getByTestId("export-deliveries")
      .getByRole("button")
      .nth(1)
      .click();
    const countInput = exportInspector.locator('input[type="number"]').first();
    await countInput.fill("20");
    await page.waitForTimeout(700);
    const outputText = await exportInspector.textContent();
    if (!outputText?.includes("20"))
      throw new Error(
        "20-output export plan is not reflected in the inspector",
      );
    assertions.push("20-output Shorts plan rendered");

    await exportInspector
      .getByRole("button", { name: "Recadrer et agrandir", exact: true })
      .click();
    const reframeSurface = page.getByTestId("visual-reframe-surface");
    await reframeSurface.waitFor({ timeout: 5000 });
    const initialTransform = await page
      .locator('[data-testid="program-monitor"] video')
      .last()
      .evaluate((node) => getComputedStyle(node).transform);
    if (initialTransform === "none")
      throw new Error("Subtitle crop is not reflected in the video monitor");
    const reframeZoom = page.getByTestId("reframe-zoom");
    await reframeZoom.fill("1.25");
    await page.waitForTimeout(350);
    const adjustedTransform = await page
      .locator('[data-testid="program-monitor"] video')
      .last()
      .evaluate((node) => getComputedStyle(node).transform);
    if (adjustedTransform === "none" || adjustedTransform === initialTransform)
      throw new Error("Visual zoom control does not update the video monitor");
    assertions.push("Live subtitle crop and visual reframe preview");

    await exportInspector
      .getByRole("button", { name: "Qualité rapide", exact: true })
      .click();
    const upscaleStatus = page.getByTestId("upscale-status");
    await upscaleStatus.waitFor({ timeout: 5000 });
    const upscaleText = await upscaleStatus.textContent();
    if (!upscaleText?.includes("→"))
      throw new Error("Upscale source and target resolution are not visible");
    assertions.push("Visible upscale source and target resolution");

    const reframeTarget = path.join(
      outputDir,
      "export-reframe-preview.png",
    );
    await page.screenshot({ path: reframeTarget });
    screenshots.push(reframeTarget);

    for (const size of sizes) {
      await app.evaluate(({ BrowserWindow }, dimensions) => {
        BrowserWindow.getAllWindows()[0].setContentSize(
          dimensions.width,
          dimensions.height,
        );
      }, size);
      await page.waitForTimeout(300);
      const audit = await page.evaluate(() => {
        const studio = document
          .querySelector('[data-testid="studio-workbench"]')
          ?.getBoundingClientRect();
        const timeline = document
          .querySelector('[data-testid="studio-timeline"]')
          ?.getBoundingClientRect();
        return {
          width: innerWidth,
          height: innerHeight,
          horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
          studioBottom: studio?.bottom ?? 0,
          timelineBottom: timeline?.bottom ?? 0,
          timelineHeight: timeline?.height ?? 0,
        };
      });
      if (audit.horizontalOverflow > 1)
        throw new Error(
          `${size.name}: ${audit.horizontalOverflow}px horizontal overflow`,
        );
      if (
        audit.timelineHeight < 219 ||
        audit.timelineBottom > audit.height + 1
      ) {
        throw new Error(
          `${size.name}: timeline is clipped (${JSON.stringify(audit)})`,
        );
      }
      const target = path.join(outputDir, `export-${size.name}.png`);
      await page.screenshot({ path: target });
      screenshots.push(target);
    }
    assertions.push(`Studio and Export passed at ${sizes.length} window sizes`);

    console.log(JSON.stringify({ ok: true, assertions, screenshots }, null, 2));
  } catch (error) {
    console.error(
      JSON.stringify({ ok: false, error: error.message, assertions }, null, 2),
    );
    process.exitCode = 1;
  } finally {
    if (app) await app.close().catch(() => {});
    process.exit(process.exitCode || 0);
  }
})();
