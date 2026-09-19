const { app, BrowserWindow, ipcMain, dialog, Menu, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const workspaceRoot = path.resolve(__dirname, "../../..");
const isDev = Boolean(process.env.VITE_DEV_SERVER_URL);
const userDataPath =
  process.env.DUBROOM_ELECTRON_USER_DATA ||
  path.join(workspaceRoot, "data", "electron-user-data");
const fileConfig = JSON.parse(
  fs.readFileSync(
    path.join(workspaceRoot, "config", "app.config.json"),
    "utf-8"
  )
);
const apiHost = process.env.DUBSTUDIO_API_HOST || fileConfig.api.host;
const apiPort = Number(process.env.DUBSTUDIO_API_PORT || fileConfig.api.port);
const desktopConfig = fileConfig.desktop;
const forceSoftwareRenderer =
  process.env.DUBROOM_SOFTWARE_RENDERER === "1" ||
  desktopConfig.software_renderer === true;
let apiProcess = null;
let mainWindow = null;
let rendererFallbackUsed = false;
let restartRequested = false;
const logPath = path.join(workspaceRoot, "projects", "electron-main.log");

fs.mkdirSync(userDataPath, { recursive: true });
app.setPath("userData", userDataPath);
const gotSingleInstanceLock = app.requestSingleInstanceLock();

function log(message) {
  try {
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(
      logPath,
      `[${new Date().toISOString()}] ${message}\n`,
      "utf-8"
    );
  } catch {
    // Logging should never block the app window.
  }
}

if (forceSoftwareRenderer) {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-gpu-compositing");
} else {
  app.commandLine.appendSwitch("enable-gpu-rasterization");
}

function createWindow() {
  log(
    `createWindow dev=${isDev} url=${
      process.env.VITE_DEV_SERVER_URL || "dist"
    }`
  );
  mainWindow = new BrowserWindow({
    width: desktopConfig.default_width,
    height: desktopConfig.default_height,
    minWidth: desktopConfig.minimum_width,
    minHeight: desktopConfig.minimum_height,
    backgroundColor: "#101317",
    title: "DubRoom Studio",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#0c0e11",
      symbolColor: "#f3f0ea",
      height: 36,
    },
    autoHideMenuBar: true,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: true,
    },
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.once("ready-to-show", () => {
    log("window ready-to-show");
    mainWindow.show();
    mainWindow.focus();
  });
  mainWindow.on("show", () => log("window show"));
  mainWindow.on("closed", () => {
    log("window closed");
    mainWindow = null;
  });
  mainWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL) => {
      log(
        `did-fail-load ${errorCode} ${errorDescription} ${validatedURL}`
      );
      if (isDev && !rendererFallbackUsed && errorCode !== -3) {
        rendererFallbackUsed = true;
        log("development server unavailable; loading the production renderer");
        void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
      }
    }
  );
  mainWindow.webContents.on("did-finish-load", () => {
    log("did-finish-load");
    void mainWindow.webContents
      .executeJavaScript(
        "JSON.stringify({innerWidth,outerWidth,devicePixelRatio,clientWidth:document.documentElement.clientWidth})",
      )
      .then((dimensions) => log(`renderer dimensions ${dimensions}`))
      .catch((error) => log(`renderer dimensions unavailable: ${error.message}`));
  });

  if (isDev) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}

if (!gotSingleInstanceLock) {
  log("second instance quit");
  app.quit();
} else {
  app.on("second-instance", () => {
    log("second instance focus existing window");
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    log("app ready");
    Menu.setApplicationMenu(null);

    ipcMain.handle("dialog:openVideo", async () => {
      const result = await dialog.showOpenDialog({
        properties: ["openFile"],
        filters: [
          {
            name: "Video files",
            extensions: ["mp4", "mkv", "mov", "webm"],
          },
        ],
      });

      return result.canceled ? null : result.filePaths[0];
    });

    ipcMain.handle("dialog:openAudio", async () => {
      const result = await dialog.showOpenDialog({
        properties: ["openFile"],
        filters: [
          {
            name: "Audio files",
            extensions: [
              "wav",
              "mp3",
              "m4a",
              "ogg",
              "flac",
              "aac",
              "webm",
              "opus",
            ],
          },
        ],
      });
      return result.canceled ? null : result.filePaths[0];
    });

    ipcMain.handle("dialog:openTranscript", async () => {
      const result = await dialog.showOpenDialog({
        properties: ["openFile"],
        filters: [
          {
            name: "DubRoom translated scripts",
            extensions: ["json", "md", "txt", "srt", "vtt"],
          },
        ],
      });
      return result.canceled ? null : result.filePaths[0];
    });

    ipcMain.handle("dialog:openRvcModel", async () => {
      const result = await dialog.showOpenDialog({
        properties: ["openFile"],
        filters: [{ name: "RVC voice models", extensions: ["pth"] }],
      });
      return result.canceled ? null : result.filePaths[0];
    });

    ipcMain.handle("dialog:openRvcIndex", async () => {
      const result = await dialog.showOpenDialog({
        properties: ["openFile"],
        filters: [{ name: "RVC index", extensions: ["index"] }],
      });
      return result.canceled ? null : result.filePaths[0];
    });

    ipcMain.handle("app:runtimeConfig", () => ({
      apiBaseUrl: `http://${apiHost}:${apiPort}`,
      workspaceRoot,
    }));

    ipcMain.handle("app:restart", () => {
      if (restartRequested) return true;
      restartRequested = true;
      log("clean restart requested");
      setTimeout(() => {
        if (apiProcess?.pid && process.platform === "win32") {
          spawnSync(
            "taskkill",
            ["/PID", String(apiProcess.pid), "/T", "/F"],
            { windowsHide: true, stdio: "ignore" },
          );
          apiProcess = null;
        } else if (apiProcess && !apiProcess.killed) {
          apiProcess.kill();
          apiProcess = null;
        }
        app.relaunch();
        app.exit(0);
      }, 180);
      return true;
    });

    ipcMain.handle("window:setTitleBarTheme", (event, palette) => {
      const targetWindow = BrowserWindow.fromWebContents(event.sender);
      const color =
        typeof palette?.color === "string" ? palette.color : "#0c0e11";
      const symbolColor =
        typeof palette?.symbolColor === "string"
          ? palette.symbolColor
          : "#f3f0ea";
      if (
        !targetWindow ||
        !/^#[0-9a-f]{6}$/i.test(color) ||
        !/^#[0-9a-f]{6}$/i.test(symbolColor)
      ) {
        return false;
      }
      targetWindow.setTitleBarOverlay({
        color,
        symbolColor,
        height: 36,
      });
      return true;
    });

    ipcMain.handle("app:revealPath", (_event, targetPath) => {
      if (
        typeof targetPath !== "string" ||
        !path.isAbsolute(targetPath) ||
        !fs.existsSync(targetPath)
      ) {
        return false;
      }
      shell.showItemInFolder(targetPath);
      return true;
    });

    // The desktop must remain usable while a cold Python runtime starts.
    createWindow();
    void ensureApiServer().catch((error) => {
      log(`ensureApiServer failed: ${error?.message || String(error)}`);
    });

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  log("before-quit");
  if (apiProcess && !apiProcess.killed) {
    apiProcess.kill();
  }
});

async function ensureApiServer() {
  log("ensureApiServer");
  if (await isApiHealthy()) {
    log("api already healthy");
    return;
  }

  const pythonExecutable = resolvePythonExecutable();
  log(`starting api with ${pythonExecutable}`);
  apiProcess = spawn(
    pythonExecutable,
    [
      "-m",
      "uvicorn",
      "services.api.app.main:app",
      "--host",
      apiHost,
      "--port",
      String(apiPort),
    ],
    {
      cwd: workspaceRoot,
      windowsHide: true,
      env: runtimeEnvironment(),
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  apiProcess.stdout?.on("data", (chunk) => {
    log(`[api] ${String(chunk).trim()}`);
  });
  apiProcess.stderr?.on("data", (chunk) => {
    log(`[api:error] ${String(chunk).trim()}`);
  });
  apiProcess.on("error", (error) => {
    log(`api process error: ${error?.message || String(error)}`);
  });
  apiProcess.on("exit", (code, signal) => {
    log(`api process exit code=${code ?? "null"} signal=${signal ?? "none"}`);
    apiProcess = null;
  });

  await waitForApi();
}

function resolvePythonExecutable() {
  const candidates = [
    process.env.DUB_STUDIO_PYTHON,
    path.join(
      workspaceRoot,
      "data",
      "environments",
      "api-runtime",
      "Scripts",
      "python.exe"
    ),
    path.join(
      workspaceRoot,
      "data",
      "environments",
      "api-runtime",
      "bin",
      "python"
    ),
  ].filter(Boolean);

  const managed = candidates.find((candidate) => fs.existsSync(candidate));
  if (managed) return managed;

  log("managed API runtime missing; falling back to python on PATH");
  return "python";
}

function resolveFfmpegBinDir() {
  const candidates = [];
  if (process.env.DUBROOM_FFMPEG_BIN) {
    candidates.push(process.env.DUBROOM_FFMPEG_BIN);
  }
  if (process.env.LOCALAPPDATA) {
    const wingetRoot = path.join(
      process.env.LOCALAPPDATA,
      "Microsoft",
      "WinGet",
      "Packages"
    );
    try {
      for (const entry of fs.readdirSync(wingetRoot, { withFileTypes: true })) {
        if (!entry.isDirectory() || !entry.name.startsWith("Gyan.FFmpeg_")) {
          continue;
        }
        const packageRoot = path.join(wingetRoot, entry.name);
        for (const version of fs.readdirSync(packageRoot, {
          withFileTypes: true,
        })) {
          if (version.isDirectory()) {
            candidates.push(path.join(packageRoot, version.name, "bin"));
          }
        }
      }
    } catch {
      // FFmpeg may simply not be installed with WinGet.
    }
  }
  return candidates.find(
    (candidate) =>
      fs.existsSync(path.join(candidate, "ffmpeg.exe")) &&
      fs.existsSync(path.join(candidate, "ffprobe.exe"))
  );
}

function runtimeEnvironment() {
  const pathKey =
    Object.keys(process.env).find((key) => key.toLowerCase() === "path") ||
    "PATH";
  const ffmpegBinDir = resolveFfmpegBinDir();
  const mergedPath = [ffmpegBinDir, process.env[pathKey]]
    .filter(Boolean)
    .join(path.delimiter);
  return {
    ...process.env,
    [pathKey]: mergedPath,
    DUBROOM_WORKSPACE_ROOT: workspaceRoot,
    HF_HUB_DISABLE_XET: "1",
    HF_HOME:
      process.env.HF_HOME ||
      path.join(workspaceRoot, "data", "cache", "huggingface"),
    TORCH_HOME:
      process.env.TORCH_HOME ||
      path.join(workspaceRoot, "data", "cache", "torch"),
    XDG_CACHE_HOME:
      process.env.XDG_CACHE_HOME ||
      path.join(workspaceRoot, "data", "cache"),
  };
}

async function waitForApi() {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (await isApiHealthy()) {
      log("api became healthy");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  log("api did not become healthy before startup timeout");
}

function isApiHealthy() {
  return new Promise((resolve) => {
    const request = http.get(
      `http://${apiHost}:${apiPort}/health`,
      (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      }
    );

    request.on("error", () => resolve(false));
    request.setTimeout(700, () => {
      request.destroy();
      resolve(false);
    });
  });
}
