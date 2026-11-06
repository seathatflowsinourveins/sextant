// The Sextant GitHub App's installation token, by GitHub's documented flow: a JWT signed with the App key,
// then POST /app/installations/{id}/access_tokens, a one-hour token. Both steps are @octokit/auth-app's,
// pinned in package-lock.json. The token reaches only a child's environment, as GH_TOKEN and
// AO_GITHUB_TOKEN; it is never printed or written. The key arrives as SEXTANT_GITHUB_APP_KEY_B64 from
// scripts/with-keys.sh, is decoded in memory, and is removed from the environment before any child starts.
//   node token.mjs installation              # prints the installation ID (not a secret), read with the JWT
//   node token.mjs run -- CMD ARGS...        # CMD runs once under a fresh token
//   node token.mjs supervise -- CMD ARGS...  # CMD is restarted under a new token before the old one expires
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createAppAuth } from "@octokit/auth-app";
import { request } from "@octokit/request";

const KEY_ENV = "SEXTANT_GITHUB_APP_KEY_B64";
const CONFIG = new URL("../github-app.json", import.meta.url);
// Restart this long before expiry, so a running command never holds a dead token.
const MARGIN_MS = 10 * 60 * 1000;

function fail(message, code = 3) {
  process.stderr.write(`github-app: ${message}\n`);
  process.exit(code);
}

function apiRequest() {
  // Tests point this at a local stand-in; nothing but a loopback URL may replace api.github.com.
  const base = process.env.SEXTANT_GITHUB_API_URL;
  if (!base) return request;
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) fail("SEXTANT_GITHUB_API_URL must be http://127.0.0.1:PORT");
  return request.defaults({ baseUrl: base });
}

function appAuth() {
  const b64 = process.env[KEY_ENV];
  delete process.env[KEY_ENV];
  if (!b64) fail(`${KEY_ENV} is missing; run me through scripts/with-keys.sh --strict -k ${KEY_ENV}`);
  const privateKey = Buffer.from(b64, "base64").toString("utf8");
  if (!privateKey.includes("PRIVATE KEY-----")) fail(`${KEY_ENV} does not decode to a PEM private key`);
  const config = JSON.parse(readFileSync(CONFIG, "utf8"));
  if (!Number.isInteger(config.app_id)) fail("github-app.json has no app_id");
  return { auth: createAppAuth({ appId: config.app_id, privateKey, request: apiRequest() }), config };
}

async function installationToken({ auth, config }) {
  if (!Number.isInteger(config.installation_id)) fail("github-app.json has no installation_id; run `just gh-app ids`");
  const { token, expiresAt } = await auth({ type: "installation", installationId: config.installation_id, refresh: true });
  return { token, expiresAt: Date.parse(expiresAt) };
}

function childEnv(token) {
  return { ...process.env, GH_TOKEN: token, AO_GITHUB_TOKEN: token };
}

function command(argv) {
  const at = argv.indexOf("--");
  const cmd = at < 0 ? [] : argv.slice(at + 1);
  if (!cmd.length) fail("usage: token.mjs run|supervise -- CMD ARGS...", 2);
  return cmd;
}

function start(cmd, token) {
  return spawn(cmd[0], cmd.slice(1), { env: childEnv(token), stdio: "inherit" });
}

function exitLike(code, signal) {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
}

async function run(cmd) {
  const app = appAuth();
  const { token } = await installationToken(app);
  const child = start(cmd, token);
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => child.kill(sig));
  child.on("error", (err) => fail(`cannot start ${cmd[0]}: ${err.code}`, 127));
  child.on("exit", exitLike);
}

async function supervise(cmd) {
  const app = appAuth();
  let child;
  let stopping = false;
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => {
      stopping = true;
      child?.kill(sig);
    });
  }
  for (;;) {
    const { token, expiresAt } = await installationToken(app);
    const renewAt = new Date(expiresAt - MARGIN_MS).toISOString();
    process.stderr.write(`github-app: started ${cmd[0]} under a new token; restarting it at ${renewAt}\n`);
    child = start(cmd, token);
    let renewing = false;
    const timer = setTimeout(() => {
      renewing = true;
      child.kill("SIGTERM");
    }, Math.max(0, expiresAt - MARGIN_MS - Date.now()));
    const [code, signal] = await new Promise((resolve) => {
      child.on("error", (err) => fail(`cannot start ${cmd[0]}: ${err.code}`, 127));
      child.on("exit", (c, s) => resolve([c, s]));
    });
    clearTimeout(timer);
    if (stopping || !renewing) exitLike(code, signal);
  }
}

async function installation() {
  const { auth } = appAuth();
  const repo = JSON.parse(readFileSync(CONFIG, "utf8")).repository;
  const { token } = await auth({ type: "app" });
  const { data } = await apiRequest()("GET /repos/{owner}/{repo}/installation", {
    owner: repo.split("/")[0],
    repo: repo.split("/")[1],
    headers: { authorization: `bearer ${token}` },
  });
  process.stdout.write(`${data.id}\n`);
}

const mode = process.argv[2];
const main = { installation: () => installation(), run: () => run(command(process.argv)), supervise: () => supervise(command(process.argv)) }[mode];
if (!main) fail("usage: token.mjs installation | run -- CMD... | supervise -- CMD...", 2);
// An error from GitHub carries its status and message; never the request headers, which hold the JWT.
main().catch((err) => fail(`${err.status ?? ""} ${err.message ?? err}`.trim(), 1));
