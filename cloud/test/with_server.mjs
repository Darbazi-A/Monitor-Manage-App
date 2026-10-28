// A fresh cloud on this computer for one test: empty storage, `wrangler dev`, the test, then stop.
//   node test/with_server.mjs test/server_test.mjs      (any command after the script works too)
import { spawn, execSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = process.env.PORT || "8799";
const here = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const state = mkdtempSync(join(tmpdir(), "stage-cloud-test-"));
const server = spawn("npx.cmd", ["wrangler", "dev", "--ip", "127.0.0.1", "--port", PORT, "--persist-to", state,
                                 "--show-interactive-dev-session=false"], { cwd: decodeURIComponent(here), shell: true });
let log = "";
const ready = new Promise((resolve, reject) => {
  const look = chunk => { log += chunk; if (/Ready on/.test(log)) resolve(); };
  server.stdout.on("data", look);
  server.stderr.on("data", look);
  server.on("exit", code => reject(new Error("wrangler stopped: " + code + "\n" + log.slice(-2000))));
  setTimeout(() => reject(new Error("wrangler did not start\n" + log.slice(-2000))), 120000);
});

function stop() {
  try { execSync(`taskkill /PID ${server.pid} /T /F`, { stdio: "ignore" }); } catch (e) { /* gone */ }
  try { rmSync(state, { recursive: true, force: true }); } catch (e) { /* busy */ }
}

let code = 1;
try {
  await ready;
  const [command, ...args] = process.argv.slice(2);
  const run = spawn(command.endsWith(".mjs") ? process.execPath : command, command.endsWith(".mjs") ? [command, ...args] : args,
                    { stdio: "inherit", env: { ...process.env, CLOUD: `http://127.0.0.1:${PORT}` }, shell: !command.endsWith(".mjs") });
  code = await new Promise(resolve => run.on("exit", resolve));
} catch (error) {
  console.error(String(error));
} finally {
  stop();
}
process.exit(code ?? 1);
