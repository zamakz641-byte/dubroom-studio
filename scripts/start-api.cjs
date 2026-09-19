const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const fileConfig = JSON.parse(
  fs.readFileSync(path.join(root, "config", "app.config.json"), "utf-8")
);
const apiHost = process.env.DUBSTUDIO_API_HOST || fileConfig.api.host || "127.0.0.1";
const apiPort = String(process.env.DUBSTUDIO_API_PORT || fileConfig.api.port || 8766);
const managedPython = path.join(
  root,
  "data",
  "environments",
  "api-runtime",
  "Scripts",
  "python.exe"
);
const python = process.env.DUB_STUDIO_PYTHON || managedPython;

if (!fs.existsSync(python)) {
  throw new Error(
    `The project-local API runtime is missing: ${python}. Launch DubRoom Studio once to repair it.`
  );
}

const child = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "services.api.app.main:app",
    "--host",
    apiHost,
    "--port",
    apiPort,
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      DUBROOM_WORKSPACE_ROOT: root,
      HF_HOME:
        process.env.HF_HOME ||
        path.join(root, "data", "cache", "huggingface"),
      TORCH_HOME:
        process.env.TORCH_HOME ||
        path.join(root, "data", "cache", "torch"),
    },
    stdio: "inherit",
  }
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}

child.on("exit", (code, signal) => {
  process.exitCode = typeof code === "number" ? code : signal ? 1 : 0;
});
