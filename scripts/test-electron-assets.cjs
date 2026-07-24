const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const outputDir = path.join(root, "output", "playwright", "electron-assets");
const screenshotPath = path.join(outputDir, "engine-logos-loaded.png");
fs.mkdirSync(outputDir, { recursive: true });

async function readLoadedLogos(page) {
  const logos = await page.locator("img[alt]").evaluateAll((images) =>
    images.map((image) => ({
      alt: image.getAttribute("alt"),
      src: image.getAttribute("src"),
      complete: image.complete,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    })),
  );
  const broken = logos.filter(
    (logo) =>
      !logo.complete || logo.naturalWidth === 0 || logo.naturalHeight === 0,
  );
  if (broken.length) {
    throw new Error(`Broken engine assets: ${JSON.stringify(broken)}`);
  }
  return logos;
}

(async () => {
  let app;
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
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("app-shell").waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "Moteurs", exact: true }).click();
    await page.getByRole("button", { name: "Traduction", exact: true }).click();

    const qwenLogo = page.getByRole("img", { name: "Qwen", exact: true });
    await qwenLogo.waitFor({ timeout: 15000 });
    await page.waitForFunction(() => {
      const image = document.querySelector('img[alt="Qwen"]');
      return image instanceof HTMLImageElement && image.naturalWidth > 0;
    });

    const translationLogos = await readLoadedLogos(page);
    if (!translationLogos.some((logo) => logo.src?.startsWith("file:") && logo.src.includes("/dist/brands/"))) {
      throw new Error(`Electron assets did not resolve inside dist: ${JSON.stringify(translationLogos)}`);
    }

    await page.screenshot({ path: screenshotPath });

    await page.getByRole("button", { name: "Tous", exact: true }).click();
    await page.waitForTimeout(300);
    const engineLogos = await readLoadedLogos(page);
    await page
      .getByRole("button", { name: "Synthèse vocale", exact: true })
      .click();
    await page.waitForTimeout(300);
    const voiceLogos = await readLoadedLogos(page);
    const logos = [...translationLogos, ...engineLogos, ...voiceLogos];
    const uniqueSources = new Set(logos.map((logo) => logo.src));
    if (uniqueSources.size < 10) {
      throw new Error(`Only ${uniqueSources.size} distinct brand assets rendered`);
    }

    console.log(
      JSON.stringify(
        {
          ok: true,
          loadedCards: logos.length,
          uniqueAssets: uniqueSources.size,
          translationLogos,
          engineLogoCount: engineLogos.length,
          voiceLogoCount: voiceLogos.length,
          screenshot: screenshotPath,
        },
        null,
        2,
      ),
    );
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
    process.exitCode = 1;
  } finally {
    if (app) await app.close().catch(() => {});
    process.exit(process.exitCode || 0);
  }
})();
