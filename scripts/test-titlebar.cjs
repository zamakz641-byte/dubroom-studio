const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const outputDir = path.join(root, "output", "playwright", "titlebar");
const screenshotPath = path.join(outputDir, "custom-titlebar.png");
const restoreScreenshotPath = path.join(
  outputDir,
  "sidebar-restore-control.png",
);
fs.mkdirSync(outputDir, { recursive: true });

(async () => {
  let app;
  const assertions = [];
  try {
    app = await electron.launch({ args: ["."], cwd: appDir, timeout: 30000 });
    const page = await app.firstWindow();
    await page.waitForLoadState("domcontentloaded");
    await page.evaluate(() => {
      localStorage.setItem("dubroom.onboardingComplete", "true");
      localStorage.setItem(
        "dubroom.onboardingResetVersion",
        "tailwind-v2-release",
      );
      localStorage.setItem("dubroom.locale", "fr");
      localStorage.setItem("dubroom.railState", "expanded");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("app-shell").waitFor({ timeout: 15000 });

    const titlebar = page.getByTestId("desktop-titlebar");
    const box = await titlebar.boundingBox();
    if (!box || box.y !== 0 || Math.round(box.height) !== 36) {
      throw new Error(`Unexpected custom titlebar geometry: ${JSON.stringify(box)}`);
    }
    assertions.push("Custom titlebar occupies the first 36px of the renderer");

    await page.getByRole("button", { name: "Fichier", exact: true }).click();
    await page.getByRole("menu").waitFor();
    await page.getByRole("menuitem", { name: /Projets/ }).click();
    const previous = page.getByRole("button", {
      name: "Page précédente",
      exact: true,
    });
    if (await previous.isDisabled()) {
      throw new Error("Titlebar history did not record section navigation");
    }
    await previous.click();
    assertions.push("File menu and Previous navigation are functional");

    await page.getByRole("button", { name: "Affichage", exact: true }).click();
    await page.getByRole("menu").getByRole("menuitem").first().click();
    await page.waitForTimeout(250);
    const railWidth = await page.locator("aside").evaluate((node) =>
      Math.round(node.getBoundingClientRect().width),
    );
    if (railWidth !== 64) {
      throw new Error(`View menu did not compact the navigation: ${railWidth}px`);
    }
    assertions.push("View menu compacts the navigation to 64px");

    await page.getByRole("button", { name: "Affichage", exact: true }).click();
    await page.getByRole("menu").getByRole("menuitem").last().click();
    await page.waitForTimeout(250);
    if ((await page.locator("aside").count()) !== 0) {
      throw new Error("Focus mode did not hide the navigation rail");
    }
    const sidebarToggle = page.getByTestId("sidebar-toggle");
    if (!(await sidebarToggle.isVisible())) {
      throw new Error("Sidebar restore control disappeared in Focus mode");
    }
    await page.screenshot({ path: restoreScreenshotPath });
    await sidebarToggle.click();
    await page.waitForTimeout(250);
    const restoredWidth = await page.locator("aside").evaluate((node) =>
      Math.round(node.getBoundingClientRect().width),
    );
    if (restoredWidth !== 64) {
      throw new Error(`Sidebar restored at an invalid width: ${restoredWidth}px`);
    }
    assertions.push("Focus mode keeps a visible one-click sidebar restore control");

    const windowState = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      const before = win.getBounds();
      win.maximize();
      const maximized = win.isMaximized();
      win.unmaximize();
      return { before, maximized, maximizable: win.isMaximizable() };
    });
    if (!windowState.maximizable || !windowState.maximized) {
      throw new Error(`Native window behavior failed: ${JSON.stringify(windowState)}`);
    }
    assertions.push("Native maximize and Windows window management remain available");

    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].setContentSize(1480, 920);
    });
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Fichier", exact: true }).click();
    await page.screenshot({ path: screenshotPath });

    console.log(
      JSON.stringify(
        {
          ok: true,
          assertions,
          titlebar: box,
          screenshot: screenshotPath,
          restoreScreenshot: restoreScreenshotPath,
        },
        null,
        2,
      ),
    );
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
