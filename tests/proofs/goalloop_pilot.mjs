// Host proof of the four goalloop assertions the census pilot required (receipt-v2):
// (a) the gate re-runs every AC check itself, (b) a completion claim is denied while the
// contract is red, (c) two caught false completes latch BLOCKED, (d) only the human CLI
// clears the latch. It drives the plugin's own documented entry points: `bin/gate.mjs` and
// the `tools/pre-execute` interceptor `apply()` registers. Usage:
//   node tests/proofs/goalloop_pilot.mjs <installed dsh-goalloop-agentteams directory>
// Source: samirliu/dsh-goalloop-agentteams@6b4b1fad8cd61f98e6eedbb4f12ed10b5dc93f17
//   bin/gate.mjs:1-80 (check|reset, exit 0 GO / 2 NO-GO / 3 BLOCKED), lib/index.js:166-260
//   (intercept: deny, BLOCKED at false-completes >= 2), :1899-1925 (tools/pre-execute).
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const PKG = path.resolve(process.argv[2] ?? '');
const GATE = path.join(PKG, 'bin/gate.mjs');
const CONTRACT = 'objective: prove the gate judges the artifact, not the claim\n'
  + 'AC-1 | the artifact is GREEN | check: `echo ran >> .goal-gate/evidence/runs.log; '
  + 'grep -q "^GREEN$" status.txt` | expected: exit=0\n';

const report = { assertions: {}, ok: false };
const fail = (name, detail) => {
  report.assertions[name] = { ok: false, detail };
  console.log(JSON.stringify(report, null, 2));
  process.exit(1);
};
const pass = (name, detail) => {
  report.assertions[name] = { ok: true, detail };
};
const workspace = () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'p10-goalloop-'));
  fs.mkdirSync(path.join(root, '.goal-gate/evidence'), { recursive: true });
  fs.writeFileSync(path.join(root, '.goal-gate/goal.md'), CONTRACT);
  fs.writeFileSync(path.join(root, 'status.txt'), 'RED\n');
  return root;
};
const check = (root) => {
  const run = spawnSync(process.execPath, [GATE, 'check', '--cwd', root], {
    encoding: 'utf8', timeout: 120_000,
  });
  let out = {};
  try { out = JSON.parse(run.stdout); } catch { /* reported below */ }
  return { rc: run.status, out, stderr: run.stderr.slice(-400) };
};
const runs = (root) => {
  const log = path.join(root, '.goal-gate/evidence/runs.log');
  return fs.existsSync(log) ? fs.readFileSync(log, 'utf8').split('\n').filter(Boolean).length : 0;
};

if (!fs.existsSync(GATE)) fail('installed', `${GATE} is missing`);
report.package = PKG;

// (a) The gate re-runs every AC check itself: the red contract's check runs on both rounds
// (the evidence log grows), NO-GO exits 2, and the same check turns GO after the artifact
// changes — no model claim is involved.
const rerunRoot = workspace();
const red = check(rerunRoot);
if (red.rc !== 2) fail('a-gate-reruns-the-check', { step: 'red', ...red });
if (runs(rerunRoot) !== 1) fail('a-gate-reruns-the-check', { step: 'red-runs', runs: runs(rerunRoot) });
fs.writeFileSync(path.join(rerunRoot, 'status.txt'), 'GREEN\n');
const green = check(rerunRoot);
if (green.rc !== 0) fail('a-gate-reruns-the-check', { step: 'green', ...green });
if (runs(rerunRoot) !== 2) fail('a-gate-reruns-the-check', { step: 'green-runs', runs: runs(rerunRoot) });
if (!(red.out.round === 1 && green.out.round === 2)) {
  fail('a-gate-reruns-the-check', { round: [red.out.round, green.out.round] });
}
pass('a-gate-reruns-the-check', { rc: [red.rc, green.rc], rounds: [red.out.round, green.out.round], runs: 2 });

// (b)-(d) A completion claim goes through the plugin's own interceptor. The fake ctx exposes
// only the six services lib/index.js reads (get, inject, logger, on, skills, tools).
const mod = await import(pathToFileURL(path.join(PKG, 'lib/index.js')).href);
const claimRoot = workspace();
const handlers = {};
const tools = [];
const ctx = {
  get: () => undefined,
  inject: (_names, fn) => { try { fn(ctx); } catch { /* no skills service */ } },
  logger: { info() {}, warn() {}, error() {}, debug() {} },
  on: (name, fn) => { handlers[name] = fn; },
  skills: undefined,
  tools: { register: (tool) => tools.push(tool.name) },
};
mod.apply(ctx, {});
const intercept = handlers['tools/pre-execute'];
if (typeof intercept !== 'function') fail('b-claim-denied-while-red', 'no tools/pre-execute handler');
const exec = {
  name: 'update_goal',
  arguments: { action: 'complete' },
  agent: { session: { header: { cwd: claimRoot } } },
};
const next = async () => ({ kind: 'allow' });
const first = await intercept(exec, next);
if (first?.kind !== 'deny' || first?.info?.code !== 'no-go') {
  fail('b-claim-denied-while-red', first);
}
pass('b-claim-denied-while-red', { code: first.info.code, reason: first.reason });

// (c) The second caught false complete latches BLOCKED; a later claim stays blocked.
const second = await intercept(exec, next);
const state = JSON.parse(fs.readFileSync(path.join(claimRoot, '.goal-gate/state.json'), 'utf8'));
if (second?.kind !== 'deny' || second?.info?.code !== 'blocked' || state.falseCompletes !== 2) {
  fail('c-two-false-completes-block', { second, falseCompletes: state.falseCompletes });
}
const third = await intercept(exec, next);
if (third?.info?.code !== 'blocked') fail('c-two-false-completes-block', { third });
pass('c-two-false-completes-block', { falseCompletes: state.falseCompletes, code: third.info.code });

// (d) The agent has no reset tool; the human CLI clears the latch, and the next claim is
// judged again (NO-GO, not BLOCKED) instead of staying frozen.
const resetTools = tools.filter((name) => name.includes('reset'));
if (resetTools.length) fail('d-reset-is-human-only', { resetTools });
const reset = spawnSync(process.execPath, [GATE, 'reset', '--cwd', claimRoot], {
  encoding: 'utf8', timeout: 120_000,
});
let resetOut = {};
try { resetOut = JSON.parse(reset.stdout); } catch { /* reported below */ }
if (reset.status !== 0 || resetOut.reset !== true) {
  fail('d-reset-is-human-only', { rc: reset.status, out: resetOut, stderr: reset.stderr.slice(-400) });
}
const after = await intercept(exec, next);
if (after?.kind !== 'deny' || after?.info?.code !== 'no-go') {
  fail('d-reset-is-human-only', { after });
}
pass('d-reset-is-human-only', { toolCount: tools.length, reset: resetOut.reset, code: after.info.code });

report.ok = true;
console.log(JSON.stringify(report, null, 2));
