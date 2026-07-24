const { _electron: electron } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const appDir = path.join(root, "apps", "desktop");
const apiBase = "http://127.0.0.1:8766";
const outputDir = path.join(root, "output", "playwright", "studio-editing");
const screenshotPath = path.join(outputDir, "real-editing-tools.png");
fs.mkdirSync(outputDir, { recursive: true });

async function request(url, options) {
  const response = await fetch(`${apiBase}${url}`, options);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

(async () => {
  let app;
  let page;
  let projectId;
  let originalTimeline;
  const assertions = [];
  try {
    app = await electron.launch({ args: ["."], cwd: appDir, timeout: 30000 });
    page = await app.firstWindow();
    await page.waitForLoadState("domcontentloaded");
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        await request("/health");
        break;
      } catch (error) {
        if (attempt === 39) throw error;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }
    const projectsPayload = await request("/projects");
    const projects = Array.isArray(projectsPayload)
      ? projectsPayload
      : projectsPayload.projects;
    const project = projects.find((item) => item.source_path);
    if (!project) throw new Error("No project with source media is available");
    projectId = project.id;
    originalTimeline = await request(`/projects/${projectId}/timeline/state`);

    await page.evaluate((activeProjectId) => {
      localStorage.setItem("dubroom.onboardingComplete", "true");
      localStorage.setItem(
        "dubroom.onboardingResetVersion",
        "tailwind-v2-release"
      );
      localStorage.setItem("dubroom.locale", "fr");
      localStorage.setItem("dubroom.activeProjectId", activeProjectId);
      localStorage.setItem("dubroom.railState", "compact");
    }, projectId);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("app-shell").waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "Studio", exact: true }).click();
    await page.getByTestId("studio-workbench").waitFor({ timeout: 20000 });

    const timelineSeparator = page.getByTestId("studio-timeline-separator");
    const timelinePanel = page.getByTestId("studio-timeline-panel");
    const orientation = await timelineSeparator.getAttribute("aria-orientation");
    if (orientation !== "horizontal") {
      throw new Error(`Timeline separator orientation is ${orientation}`);
    }
    const beforeResize = await timelinePanel.boundingBox();
    await timelineSeparator.focus();
    await timelineSeparator.press("ArrowUp");
    await timelineSeparator.press("ArrowUp");
    await page.waitForTimeout(120);
    const afterResize = await timelinePanel.boundingBox();
    if (
      !beforeResize ||
      !afterResize ||
      afterResize.height <= beforeResize.height + 1
    ) {
      throw new Error("Keyboard resize did not expand the timeline panel");
    }
    assertions.push("Timeline panel resizes with an accessible keyboard separator");

    const sourceClips = page.getByTestId("edit-clip");
    const beforeCount = await sourceClips.count();
    const monitorRange = page
      .getByTestId("program-monitor")
      .locator('input[type="range"]');
    const duration = Number(await monitorRange.getAttribute("max"));
    const persistedClips = originalTimeline.edit_initialized
      ? originalTimeline.edit_clips.filter((clip) => clip.enabled)
      : [{ source_start: 0, source_end: duration }];
    const splittable = persistedClips.find(
      (clip) => clip.source_end - clip.source_start > 0.2
    );
    if (!splittable) throw new Error("No source clip can be split");
    const splitTime = Number(
      (
        splittable.source_start +
        (splittable.source_end - splittable.source_start) / 2
      ).toFixed(2)
    );
    await monitorRange.fill(String(splitTime));
    await page
      .getByTestId("edit-toolbar")
      .getByTitle("Couper au curseur")
      .click();
    await page.waitForFunction(
      (count) =>
        document.querySelectorAll('[data-testid="edit-clip"]').length ===
        count + 1,
      beforeCount
    );
    assertions.push("Split at playhead creates two persistent source clips");

    const persisted = await request(`/projects/${projectId}/timeline/state`);
    if (
      persisted.version !== 3 ||
      !persisted.edit_initialized ||
      persisted.edit_clips.length !== beforeCount + 1
    ) {
      throw new Error(
        `Invalid persisted edit state: ${JSON.stringify(persisted)}`
      );
    }
    assertions.push("Timeline V3 edit decision list persisted through the API");

    await page.getByTestId("timeline-scroll").evaluate((node, at) => {
      const pixelsPerSecond = 48;
      const trackHeaderWidth = 160;
      node.scrollLeft = Math.max(
        0,
        trackHeaderWidth + at * pixelsPerSecond - node.clientWidth / 2
      );
    }, splitTime);

    const mute = page
      .getByTestId("studio-timeline")
      .getByTitle("Couper le son de la piste")
      .first();
    await mute.click();
    await page.waitForTimeout(250);
    const mutedState = await request(`/projects/${projectId}/timeline/state`);
    if (!mutedState.track_states.original?.muted) {
      throw new Error("Original audio track mute was not persisted");
    }
    assertions.push("Track mute state is persisted and available to export");

    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].setContentSize(1480, 920);
    });
    await page.waitForTimeout(300);
    await page.screenshot({ path: screenshotPath });
    console.log(
      JSON.stringify(
        { ok: true, assertions, screenshot: screenshotPath },
        null,
        2
      )
    );
  } catch (error) {
    console.error(
      JSON.stringify({ ok: false, error: error.message, assertions }, null, 2)
    );
    process.exitCode = 1;
  } finally {
    if (projectId && originalTimeline) {
      await fetch(`${apiBase}/projects/${projectId}/timeline/state`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(originalTimeline),
      }).catch(() => {});
    }
    if (app) await app.close().catch(() => {});
    process.exit(process.exitCode || 0);
  }
})();
