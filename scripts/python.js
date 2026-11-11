"use strict";
const { spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const python = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", shell: false });
  if (result.error || result.status !== 0) {
    console.error("Python command failed. Install Python 3.10+ with venv support, or set VWCAR_PYTHON to its executable path and run npm install again.");
    process.exit(result.status || 1);
  }
}
const action = process.argv[2];
if (action === "setup") {
  if (!existsSync(python)) run(process.env.VWCAR_PYTHON || (process.platform === "win32" ? "py" : "python3"), ["-m", "venv", ".venv"]);
  run(python, ["-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"]);
} else if (!existsSync(python)) {
  console.error("Local Python environment missing. Run npm install first.");
  process.exitCode = 1;
} else if (action === "probe") run(python, ["scripts/probe.py"]);
else if (action === "test") run(python, ["-m", "unittest", "discover", "-s", "test", "-v"]);
else if (action === "check") run(python, ["-m", "compileall", "-q", "scripts", "test"]);
else { console.error("Unknown action."); process.exitCode = 1; }
