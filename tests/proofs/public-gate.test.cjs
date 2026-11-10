// Native node:test pattern already used by workflow-scenarios.mjs; no provider or GitHub calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const gate = require('../../.github/gate/gate.cjs');

test('ordinary PRs never select an API-key reviewer', () => {
  for (const author of ['', 'codex', 'claude', 'muse', 'agy']) {
    assert.equal(gate.route(author ? `Agent-Family ${author}` : '', [{filename: 'docs/example.md'}]).quality, '');
  }
  assert.throws(() => gate.route('Agent-Family codex\nReview-Family claude', []));
  assert.throws(() => gate.route('Agent-Family claude\nReview-Family codex', []));
});

test('dsh authors get Codex by default and Claude only when selected', () => {
  assert.equal(gate.route('Agent-Family dsh', []).quality, 'codex');
  assert.equal(gate.route('Agent-Family dsh\nReview-Family codex', []).quality, 'codex');
  assert.equal(gate.route('Agent-Family dsh\nReview-Family claude', []).quality, 'claude');
  assert.throws(() => gate.route('Agent-Family dsh\nReview-Family dsh', []));
});

test('every owner-named risk prefix selects exactly one extra other-family review', () => {
  for (const prefix of ['src/sextant/execution/', 'src/sextant/exits/', 'src/sextant/paper/',
    'src/sextant/risk/', 'src/sextant/alpaca/', 'lanes/paper/', 'lanes/live/', 'deploy/live/',
    'config/dsh/review-cmd/', '.github/']) {
    for (const field of ['filename', 'previous_filename']) {
      const files = [{filename: 'docs/moved.txt', [field]: `${prefix}example.py`}];
      assert.equal(gate.route('Agent-Family codex', files).quality, 'claude', `${prefix}:${field}`);
      assert.equal(gate.route('Agent-Family claude', files).quality, 'codex', `${prefix}:${field}`);
      assert.equal(gate.route('Agent-Family dsh', files).quality, 'codex', `${prefix}:${field}`);
    }
  }
  assert.equal(gate.route('Agent-Family codex', [{filename: 'src/sextant/riskier/example.py'}]).quality, '');
  assert.equal(gate.route('Agent-Family claude', [{filename: 'dangerfile.js'}]).quality, 'codex');
  assert.equal(gate.route('Agent-Family codex\nReview-Family claude', [{filename: '.github/workflows/ci.yml'}]).quality, 'claude');
});

test('ambiguous, malformed and conflicting markers fail closed', () => {
  for (const body of ['Agent-Family <family>', 'Agent-Family: dsh', 'Agent-Family  dsh',
    'Agent-Family codex\nAgent-Family dsh', 'Review-Family codex',
    'Agent-Family codex\nReview-Family codex', 'Agent-Family dsh\nReview-Family opus',
    'Agent-Family dsh\nReview-Family claude\nReview-Family codex',
    'Agent-Family codex2', 'Agent-Family dsh_foo', 'Agent-Family codexX',
    'Agent-Family dsh\nReview-Family codex2']) assert.throws(() => gate.route(body, []), body);
});

function fixture() {
  const head = 'a'.repeat(40);
  const statuses = [], outputs = {}, failures = [], reviews = [];
  const pr = {number: 7, state: 'open', head: {sha: head}, base: {ref: 'gate', repo: {full_name: 'owner/project'}}};
  const github = {rest: {
    pulls: {get: async () => ({data: pr}), listReviews: 'reviews',
      createReview: async args => reviews.push(args)},
    repos: {get: async () => ({data: {full_name: 'owner/project', default_branch: 'gate'}}),
      createCommitStatus: async status => statuses.push(status)},
  }, paginate: async () => []};
  const context = {repo: {owner: 'owner', repo: 'project'}, serverUrl: 'https://github.com', runId: 12,
    payload: {workflow_run: {conclusion: 'success'}}};
  const core = {setOutput: (name, value) => {outputs[name] = value;}, setFailed: value => failures.push(value)};
  return {github, context, core, head, pr, statuses, outputs, failures, reviews};
}

test('source status cannot pass a moved head or failed CI', async () => {
  const f = fixture();
  f.pr.head.sha = 'b'.repeat(40);
  await gate.sourceResult(f, 7, f.head, 'success');
  assert.equal(f.statuses[0].state, 'failure');
  assert.equal(f.statuses[0].sha, f.head);
  assert.equal(f.outputs.ready, 'false');
  f.pr.head.sha = f.head;
  f.context.payload.workflow_run.conclusion = 'failure';
  await gate.sourceResult(f, 7, f.head, 'success');
  assert.equal(f.outputs.ready, 'false');
});

test('aggregate review requires dsh and every selected quality job', async () => {
  for (const [quality, results, expected] of [
    ['', {source: 'success', dsh: 'success', codex: 'skipped', claude: 'skipped'}, 'success'],
    ['', {source: 'success', dsh: 'failure'}, 'failure'],
    ['codex', {source: 'success', dsh: 'success', codex: 'skipped'}, 'failure'],
    ['codex', {source: 'success', dsh: 'success', codex: 'success'}, 'success'],
    ['claude', {source: 'success', dsh: 'success', claude: 'failure'}, 'failure'],
    ['', {source: 'failure', dsh: 'success'}, 'failure'],
  ]) {
    const f = fixture();
    await gate.finish(f, 7, f.head, results, quality);
    assert.equal(f.statuses[0].state, expected);
    assert.equal(f.statuses[0].sha, f.head);
    assert.equal(f.statuses[0].context, 'review');
  }
});

test('third-head mapping leaves P1 and lower nonblocking but keeps P0 blocking', () => {
  const report = priority => ({findings: [{title: `[P${priority}] Witness`, body: 'file:1, input, wrong output', priority}],
    overall_correctness: 'patch is incorrect', overall_explanation: 'A concrete witness.'});
  assert.equal(gate.qualityPassed(report(1)), false);
  assert.equal(gate.qualityPassed(report(1), 0), true);
  assert.equal(gate.qualityPassed(report(0), 0), false);
  assert.equal(gate.qualityPassed(report(2)), true);
});

// #205's Codex final message, verbatim: the action succeeded, but the review did not run.
const HOLLOW_205 = '{"findings": [], "overall_correctness": "patch is incorrect", ' +
  '"overall_explanation": "Review of 2f023a0653baba6801a2ea9ffcf559a9bd10c208 could not be completed: ' +
  'GitHub CLI authentication is unavailable and api.github.com does not resolve. Required context and ' +
  'upstream sources could not be verified; this reports a review failure, not a demonstrated patch defect.", ' +
  '"overall_confidence_score": 0.03}';

test('a review that could not run fails closed with its network cause (#205 fixture)', async () => {
  const f = fixture();
  await gate.qualityResult(f, 7, f.head, HOLLOW_205, 'codex');
  assert.equal(f.outputs.passed, 'false');
  assert.equal(f.reviews.length, 0);
  assert.equal(f.failures.length, 1);
  assert.match(f.failures[0], /^Review could not be completed/);
  assert.match(f.failures[0], /network or authentication fault/);
  assert.match(f.failures[0], /GitHub CLI authentication is unavailable/);
});

test('missing and unreadable verdicts fail closed with named reasons', async () => {
  for (const [text, reason] of [
    ['', /verdict is missing/i],
    ['not json', /verdict is unreadable/i],
    ['{"findings": [], "overall_correctness": "unknown", "overall_explanation": "x"}', /verdict is unreadable/i],
  ]) {
    const f = fixture();
    await gate.qualityResult(f, 7, f.head, text, 'codex');
    assert.equal(f.outputs.passed, 'false');
    assert.equal(f.reviews.length, 0);
    assert.equal(f.failures.length, 1);
    assert.match(f.failures[0], reason);
  }
});

test('a valid structured verdict still posts one review and passes', async () => {
  const f = fixture();
  const text = JSON.stringify({findings: [], overall_correctness: 'patch is correct',
    overall_explanation: 'No blocking findings.'});
  await gate.qualityResult(f, 7, f.head, text, 'codex');
  assert.equal(f.failures.length, 0);
  assert.equal(f.outputs.passed, 'true');
  assert.equal(f.reviews.length, 1);
  assert.match(f.reviews[0].body, new RegExp(`^Review of ${f.head}`));
});

test('the API-only guard refuses execution and publishing for another head or PR', async () => {
  const {refusal} = await import('../../.github/gate/bundles/api-only/index.mjs');
  const env = {DSH_GATE_REPO: 'owner/project', DSH_GATE_PR: '7', DSH_GATE_HEAD: 'a'.repeat(40)};
  for (const name of ['bash', 'pwsh', 'write', 'edit', 'apply_patch', 'terminal_send']) assert.ok(refusal({name}, env));
  assert.equal(refusal({name: 'gh_file'}, env), undefined);
  const args = {task: 'publish', pr: 'owner/project#7', body: `Review of ${env.DSH_GATE_HEAD}`, findings: []};
  assert.equal(refusal({name: 'ci_run', arguments: args}, env), undefined);
  assert.ok(refusal({name: 'ci_run', arguments: {...args, pr: '8'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, pr: '7', ownerRepo: 'owner/project'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, pr: 'another/repo#7'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, task: 'review'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, body: 'Review of another head'}}, env));
});

test('the actual dsh prompt uses the upstream qualified PR reference accepted by its guard', async () => {
  const f = fixture();
  const temporary = fs.mkdtempSync(path.join(process.cwd(), '.gate-prompt-test-'));
  const previous = process.env.RUNNER_TEMP;
  process.env.RUNNER_TEMP = temporary;
  try {
    await gate.prompt(f, 7, f.head, 'dsh');
    const match = f.outputs.text.match(/first call ci_run with (\{[^\n]*?\})/);
    assert.ok(match);
    const args = JSON.parse(match[1]);
    assert.deepEqual(args, {task: 'analyze', pr: 'owner/project#7'});
    const {refusal} = await import('../../.github/gate/bundles/api-only/index.mjs');
    assert.equal(refusal({name: 'ci_run', arguments: args},
      {DSH_GATE_REPO: 'owner/project', DSH_GATE_PR: '7', DSH_GATE_HEAD: f.head}), undefined);
  } finally {
    if (previous === undefined) delete process.env.RUNNER_TEMP;
    else process.env.RUNNER_TEMP = previous;
    fs.rmSync(temporary, {recursive: true, force: true});
  }
});

test('all nonblocking findings share one follow-up issue across heads and families', async () => {
  const f = fixture(), issues = [];
  let creates = 0, updates = 0;
  f.github.rest.issues = {
    listForRepo: 'issues',
    create: async args => {creates++; issues.push({...args, number: 9, user: {login: 'github-actions[bot]'}});},
    update: async args => {updates++; Object.assign(issues[0], args);},
  };
  f.github.paginate = async () => issues;
  const notes = {dsh: JSON.stringify(['[P2] docs follow-up']), codex: JSON.stringify(['[P3] style follow-up'])};
  await gate.followupIssue(f.github, f.context, 7, f.head, notes);
  await gate.followupIssue(f.github, f.context, 7, f.head, notes);
  await gate.followupIssue(f.github, f.context, 7, 'b'.repeat(40), notes);
  assert.equal(creates, 1);
  assert.equal(updates, 1);
  assert.match(issues[0].body, /docs follow-up/);
  assert.match(issues[0].body, /style follow-up/);
  assert.match(issues[0].body, new RegExp('b'.repeat(40)));
});

test('review attempt repeats do not count as another reviewed commit', async () => {
  const f = fixture();
  const review = sha => ({user: {login: 'github-actions[bot]'}, body: `Review of ${sha}`});
  f.github.paginate = async () => [review('b'.repeat(40)), review('b'.repeat(40)), review(f.head),
    {user: {login: 'someone'}, body: `Review of ${'c'.repeat(40)}`}];
  assert.equal(await gate.blockingPriority(f.github, f.context, 7, f.head), 1);
  f.github.paginate = async () => [review('b'.repeat(40)), review('c'.repeat(40))];
  assert.equal(await gate.blockingPriority(f.github, f.context, 7, f.head), 0);
});
