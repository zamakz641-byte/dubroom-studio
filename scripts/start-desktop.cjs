const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const rootDir = path.resolve(__dirname, "..");
const appDir = path.join(rootDir, "apps", "desktop");
const projectsDir = path.join(rootDir, "projects");
const electronExe = path.join(rootDir, "node_modules", "electron", "dist", "electron.exe");

fs.mkdirSync(projectsDir, { recursive: true });

function logLine(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(path.join(projectsDir, "desktop-launcher.log"), line, "utf-8");
  process.stdout.write(message + "\n");
}

function launchElectron() {
  if (!fs.existsSync(electronExe)) {
    throw new Error(`Electron executable not found: ${electronExe}`);
  }

  const indexHtml = path.join(appDir, "dist", "index.html");
  if (!fs.existsSync(indexHtml)) {
    throw new Error("Desktop build is missing. Run npm run build first.");
  }

  const stdout = fs.openSync(path.join(projectsDir, "electron-launcher.out.log"), "a");
  const stderr = fs.openSync(path.join(projectsDir, "electron-launcher.err.log"), "a");
  const env = { ...process.env };
  delete env.VITE_DEV_SERVER_URL;

  const child = spawn(electronExe, ["."], {
    cwd: appDir,
    detached: true,
    // This is the interactive desktop window, not a background helper.
    windowsHide: false,
    env,
    stdio: ["ignore", stdout, stderr]
  });
  child.unref();
  logLine(`Started Electron pid=${child.pid} cwd=${appDir}`);
}

(async () => {
  try {
    launchElectron();
  } catch (error) {
    logLine(`Launch failed: ${error && error.message ? error.message : String(error)}`);
    process.exitCode = 1;
  }
})();
