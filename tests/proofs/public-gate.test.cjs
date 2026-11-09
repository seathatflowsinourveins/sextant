// Native node:test pattern already used by workflow-scenarios.mjs; no provider or GitHub calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
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
    'src/sextant/risk/', 'src/sextant/alpaca/', 'lanes/paper/', 'lanes/live/', 'deploy/live/', '.github/']) {
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
    'Agent-Family dsh\nReview-Family claude\nReview-Family codex']) assert.throws(() => gate.route(body, []), body);
});

function fixture() {
  const head = 'a'.repeat(40);
  const statuses = [], outputs = {}, failures = [];
  const pr = {number: 7, state: 'open', head: {sha: head}, base: {ref: 'gate', repo: {full_name: 'owner/project'}}};
  const github = {rest: {
    pulls: {get: async () => ({data: pr}), listReviews: 'reviews'},
    repos: {get: async () => ({data: {full_name: 'owner/project', default_branch: 'gate'}}),
      createCommitStatus: async status => statuses.push(status)},
  }, paginate: async () => []};
  const context = {repo: {owner: 'owner', repo: 'project'}, serverUrl: 'https://github.com', runId: 12,
    payload: {workflow_run: {conclusion: 'success'}}};
  const core = {setOutput: (name, value) => {outputs[name] = value;}, setFailed: value => failures.push(value)};
  return {github, context, core, head, pr, statuses, outputs, failures};
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

test('the API-only guard refuses execution and publishing for another head or PR', async () => {
  const {refusal} = await import('../../.github/gate/bundles/api-only/index.mjs');
  const env = {DSH_GATE_REPO: 'owner/project', DSH_GATE_PR: '7', DSH_GATE_HEAD: 'a'.repeat(40)};
  for (const name of ['bash', 'pwsh', 'write', 'edit', 'apply_patch', 'terminal_send']) assert.ok(refusal({name}, env));
  assert.equal(refusal({name: 'gh_file'}, env), undefined);
  const args = {task: 'publish', pr: '7', ownerRepo: 'owner/project', body: `Review of ${env.DSH_GATE_HEAD}`, findings: []};
  assert.equal(refusal({name: 'ci_run', arguments: args}, env), undefined);
  assert.ok(refusal({name: 'ci_run', arguments: {...args, pr: '8'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, task: 'review'}}, env));
  assert.ok(refusal({name: 'ci_run', arguments: {...args, body: 'Review of another head'}}, env));
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
